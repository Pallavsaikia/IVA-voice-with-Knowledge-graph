import os
import asyncio
from typing import Dict, List, Any, Optional, Tuple, TypedDict
from dataclasses import dataclass
from enum import Enum

import psycopg2
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from llama_index.core import VectorStoreIndex, Document, Settings
from llama_index.core.schema import QueryBundle
from llama_index.core.retrievers import BaseRetriever
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.query_engine import RetrieverQueryEngine

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


class ReflectionState(Enum):
    INITIAL = "initial"
    REFLECTING = "reflecting"
    REFINED = "refined"
    FINAL = "final"


@dataclass
class TableSchema:
    name: str
    columns: List[str]
    relationships: Dict[str, str]  # foreign_key: referenced_table
    description: str


# Use TypedDict instead of Pydantic BaseModel for LangGraph compatibility
class RAGState(TypedDict):
    query: str
    table_schemas: List[TableSchema]
    selected_tables: List[str]
    sql_query: str
    query_results: List[Dict]
    context_documents: List[Document]
    initial_response: str
    reflection_feedback: str
    refined_response: str
    final_response: str
    reflection_state: str
    iteration_count: int
    max_iterations: int


class PostgreSQLRAGSystem:
    def __init__(self, 
                 azure_endpoint: str = None,
                 azure_api_key: str = None,
                 azure_api_version: str = None,
                 azure_deployment_name: str = None,
                 azure_embedding_deployment: str = None,
                 db_connection_string: str = None,
                 table_descriptions: Dict[str, str] = None):
        
        # Load environment variables
        load_dotenv()
        
        # Azure OpenAI configuration
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_api_key = azure_api_key or os.getenv("AZURE_OPENAI_KEY")
        self.azure_api_version = azure_api_version or os.getenv("AZURE_OPENAI_VERSION", "2024-02-15-preview")
        self.azure_deployment_name = azure_deployment_name or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.azure_embedding_deployment = azure_embedding_deployment or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        
        # Validate required configurations
        self._validate_config()
        
        # Database configuration
        self.db_connection_string = db_connection_string or os.getenv("DATABASE_URL")
        self.engine = create_engine(self.db_connection_string)
        
        # Initialize LlamaIndex components with Azure OpenAI
        try:
            # Configure LLM
            Settings.llm = AzureOpenAI(
                model="gpt-4o-mini",
                deployment_name="gpt-4o-mini",
                api_key=os.getenv("AZURE_OPENAI_KEY"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_version="2023-07-01-preview",
            )

            # Configure embedding model with explicit Azure settings
            Settings.embed_model = AzureOpenAIEmbedding(
                model="text-embedding-ada-002",
                deployment_name="text-embedding-ada-002",
                api_key=os.getenv("AZURE_OPENAI_KEY"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_version="2023-07-01-preview",
            )
            # Test the embedding configuration
            print("🧪 Testing embedding configuration...")
            test_embedding = Settings.embed_model.get_text_embedding("test")
            print(f"✅ Embedding test successful (dimension: {len(test_embedding)})")
            
            print("✅ Azure OpenAI configuration successful")
            
        except Exception as e:
            print(f"❌ Error configuring Azure OpenAI: {e}")
            print("🔧 Trying alternative embedding configuration...")
            
        self.table_descriptions = table_descriptions or {}
        
        # Load table schemas first
        print("📋 Loading table schemas...")
        self.table_schemas = self._load_table_schemas()
        
        # Create table indices (with better error handling)
        print("🔍 Creating vector indices...")
        self.table_indices = self._create_table_indices()
        
        # Initialize memory BEFORE creating workflow
        print("💾 Initializing memory...")
        self.memory = MemorySaver()
        
        # Initialize LangGraph
        print("🔗 Setting up workflow...")
        self.workflow = self._create_workflow()
        
        print("✅ RAG System initialization complete!")
    
    def _validate_config(self):
        """Validate Azure OpenAI configuration"""
        required_vars = [
            ("AZURE_OPENAI_ENDPOINT", self.azure_endpoint),
            ("AZURE_OPENAI_KEY", self.azure_api_key),
            ("AZURE_OPENAI_DEPLOYMENT", self.azure_deployment_name),
            ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", self.azure_embedding_deployment)
        ]
        
        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value:
                missing_vars.append(var_name)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Validate endpoint format
        if not self.azure_endpoint.startswith(('https://', 'http://')):
            raise ValueError("Azure endpoint must start with https:// or http://")
        
        print("✅ Configuration validation passed")
    
    def _load_table_schemas(self) -> List[TableSchema]:
        """Load PostgreSQL table schemas"""
        schemas = []
        
        # Query to get table information
        table_query = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns 
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position;
        """
        
        # Query to get foreign key relationships
        fk_query = """
        SELECT 
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name
        FROM information_schema.table_constraints AS tc 
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY';
        """
        
        try:
            with self.engine.connect() as conn:
                # Get table structures
                table_df = pd.read_sql(table_query, conn)
                fk_df = pd.read_sql(fk_query, conn)
                
                if table_df.empty:
                    print("⚠️ No tables found in the database")
                    return schemas
                
                # Group by table
                for table_name in table_df['table_name'].unique():
                    table_cols = table_df[table_df['table_name'] == table_name]
                    columns = table_cols['column_name'].tolist()
                    
                    # Get relationships
                    table_fks = fk_df[fk_df['table_name'] == table_name]
                    relationships = dict(zip(table_fks['column_name'], 
                                           table_fks['foreign_table_name']))
                    
                    schema = TableSchema(
                        name=table_name,
                        columns=columns,
                        relationships=relationships,
                        description=self.table_descriptions.get(table_name, f"Table: {table_name}")
                    )
                    schemas.append(schema)
                
                print(f"✅ Loaded {len(schemas)} table schemas")
                
        except Exception as e:
            print(f"❌ Error loading table schemas: {e}")
            raise
        
        return schemas
    
    def _create_table_indices(self) -> Dict[str, VectorStoreIndex]:
        """Create vector indices for each table's sample data with better error handling"""
        indices = {}
        
        if not self.table_schemas:
            print("⚠️ No table schemas available for indexing")
            return indices
        
        if Settings.embed_model is None:
            print("⚠️ No embedding model available, skipping vector index creation")
            return indices
        
        for schema in self.table_schemas:
            try:
                print(f"📊 Creating index for table: {schema.name}")
                
                # Sample data from each table for context
                sample_query = f"SELECT * FROM {schema.name} LIMIT 100"
                
                with self.engine.connect() as conn:
                    sample_df = pd.read_sql(sample_query, conn)
                    
                    if sample_df.empty:
                        print(f"⚠️ No data found in table {schema.name}")
                        continue
                    
                    # Create documents from sample data
                    documents = []
                    for idx, row in sample_df.iterrows():
                        content = f"Table: {schema.name}\n"
                        content += f"Description: {schema.description}\n"
                        content += f"Columns: {', '.join(schema.columns)}\n"
                        content += f"Sample data: {row.to_dict()}\n"
                        
                        doc = Document(
                            text=content,
                            metadata={
                                "table_name": schema.name,
                                "row_id": row.get('id', str(idx))
                            }
                        )
                        documents.append(doc)
                    
                    if documents:
                        # Test embedding creation first
                        print(f"🔄 Creating embeddings for {len(documents)} documents...")
                        
                        # Create index with explicit embedding model
                        indices[schema.name] = VectorStoreIndex.from_documents(
                            documents,
                            embed_model=Settings.embed_model
                        )
                        print(f"✅ Successfully created index for {schema.name}")
                    else:
                        print(f"⚠️ No documents created for table {schema.name}")
                
            except Exception as e:
                print(f"❌ Error creating index for table {schema.name}: {e}")
                # Continue with other tables instead of failing completely
                continue
        
        print(f"✅ Created {len(indices)} table indices")
        return indices
    
    def _create_workflow(self) -> StateGraph:
        """Create LangGraph workflow for RAG with self-reflection"""
        workflow = StateGraph(dict)  # Use dict instead of RAGState class
        
        # Define nodes
        workflow.add_node("analyze_query", self._analyze_query_node)
        workflow.add_node("retrieve_context", self._retrieve_context_node)
        workflow.add_node("generate_response", self._generate_response_node)
        workflow.add_node("reflect_response", self._reflect_response_node)
        workflow.add_node("refine_response", self._refine_response_node)
        
        # Define edges
        workflow.add_edge("analyze_query", "retrieve_context")
        workflow.add_edge("retrieve_context", "generate_response")
        workflow.add_conditional_edges(
            "generate_response",
            self._should_reflect,
            {
                "reflect": "reflect_response",
                "end": END
            }
        )
        workflow.add_edge("reflect_response", "refine_response")
        workflow.add_conditional_edges(
            "refine_response",
            self._should_continue_reflection,
            {
                "continue": "retrieve_context",
                "end": END
            }
        )
        
        workflow.set_entry_point("analyze_query")
        
        return workflow.compile(checkpointer=self.memory)
    
    def _analyze_query_node(self, state: Dict) -> Dict:
        """Analyze user query and select relevant tables"""
        query = state.get("query", "")
        
        # Use LLM to determine relevant tables
        table_info = "\n".join([
            f"- {schema.name}: {schema.description} (columns: {', '.join(schema.columns)})"
            for schema in self.table_schemas
        ])
        
        analysis_prompt = f"""
        Given the user query: "{query}"
        
        Available tables:
        {table_info}
        
        Select the most relevant tables for answering this query.
        Return only the table names, separated by commas.
        """
        
        try:
            # Use synchronous completion instead of async
            llm_response = Settings.llm.complete(analysis_prompt)
            selected_tables = [t.strip() for t in str(llm_response).split(',')]
            # Filter out any invalid table names
            valid_tables = [t for t in selected_tables if any(s.name == t for s in self.table_schemas)]
            
            state["selected_tables"] = valid_tables
            state["table_schemas"] = [s for s in self.table_schemas if s.name in valid_tables]
            
        except Exception as e:
            print(f"❌ Error in query analysis: {e}")
            # Fallback: select all available tables
            state["selected_tables"] = [s.name for s in self.table_schemas]
            state["table_schemas"] = self.table_schemas
        
        return state
    
    def _retrieve_context_node(self, state: Dict) -> Dict:
        """Retrieve relevant context from selected tables"""
        documents = []
        query_results = []
        selected_tables = state.get("selected_tables", [])
        query = state.get("query", "")
        
        for table_name in selected_tables:
            try:
                # Vector search (only if index exists)
                if table_name in self.table_indices:
                    index = self.table_indices[table_name]
                    retriever = index.as_retriever(similarity_top_k=5)
                    
                    query_bundle = QueryBundle(query)
                    nodes = retriever.retrieve(query_bundle)
                    
                    for node in nodes:
                        documents.append(Document(
                            text=node.text,
                            metadata=node.metadata
                        ))
                
                # Also get fresh data via SQL
                schema = next((s for s in self.table_schemas if s.name == table_name), None)
                if schema:
                    try:
                        # Generate SQL query using LLM
                        sql_prompt = f"""
                        Generate a PostgreSQL query for table "{table_name}" with columns: {', '.join(schema.columns)}
                        User Query: {query}
                        
                        Requirements:
                        - Use proper PostgreSQL syntax
                        - Limit results to 50 rows maximum
                        - Return only the SQL query, no explanation
                        - If the query is about finding the most recent, use ORDER BY with appropriate date/timestamp column DESC
                        
                        SQL Query:
                        """
                        
                        # Use synchronous completion
                        sql_response = Settings.llm.complete(sql_prompt)
                        sql_query = str(sql_response).strip()
                        
                        # Clean up the SQL query
                        sql_query = sql_query.replace('```sql', '').replace('```', '').strip()
                        
                        with self.engine.connect() as conn:
                            result_df = pd.read_sql(sql_query, conn)
                            query_results.extend(result_df.to_dict('records'))
                        
                        state["sql_query"] = sql_query
                        print(f"✅ Successfully executed SQL for {table_name}: {len(result_df)} rows")
                        
                    except Exception as sql_error:
                        print(f"❌ SQL error for {table_name}: {sql_error}")
                        # Fallback: simple select query
                        try:
                            fallback_query = f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 10"
                            with self.engine.connect() as conn:
                                result_df = pd.read_sql(fallback_query, conn)
                                query_results.extend(result_df.to_dict('records'))
                            state["sql_query"] = fallback_query
                            print(f"✅ Fallback query successful for {table_name}")
                        except Exception as fallback_error:
                            print(f"❌ Fallback query also failed for {table_name}: {fallback_error}")
                
            except Exception as e:
                print(f"❌ Error retrieving context for {table_name}: {e}")
                continue
        
        state["context_documents"] = documents
        state["query_results"] = query_results
        
        return state
    
    def _generate_response_node(self, state: Dict) -> Dict:
        """Generate initial response using retrieved context"""
        context_documents = state.get("context_documents", [])
        query_results = state.get("query_results", [])
        query = state.get("query", "")
        reflection_state = state.get("reflection_state", ReflectionState.INITIAL.value)
        
        context_text = "\n".join([doc.text for doc in context_documents])
        query_results_text = str(query_results) if query_results else "No query results"
        
        response_prompt = f"""
        User Query: {query}
        
        Retrieved Context:
        {context_text}
        
        Query Results:
        {query_results_text}
        
        Provide a comprehensive answer to the user's query based on the available information.
        """
        
        try:
            # Use synchronous completion
            response = Settings.llm.complete(response_prompt)
            
            if reflection_state == ReflectionState.INITIAL.value:
                state["initial_response"] = str(response)
            else:
                state["refined_response"] = str(response)
                
        except Exception as e:
            print(f"❌ Error generating response: {e}")
            error_response = f"I apologize, but I encountered an error while generating the response: {str(e)}"
            if reflection_state == ReflectionState.INITIAL.value:
                state["initial_response"] = error_response
            else:
                state["refined_response"] = error_response
        
        return state
    
    def _reflect_response_node(self, state: Dict) -> Dict:
        """Reflect on the generated response and provide feedback"""
        current_response = state.get("refined_response") or state.get("initial_response", "")
        query = state.get("query", "")
        selected_tables = state.get("selected_tables", [])
        sql_query = state.get("sql_query", "")
        query_results = state.get("query_results", [])
        
        reflection_prompt = f"""
        Original Query: {query}
        
        Generated Response:
        {current_response}
        
        Available Data Context:
        - Selected tables: {', '.join(selected_tables)}
        - SQL Query used: {sql_query}
        - Number of results: {len(query_results)}
        
        Analyze this response for:
        1. Accuracy and completeness
        2. Relevance to the query
        3. Use of available data
        4. Missing information that could be retrieved
        
        Provide specific feedback on how to improve the response.
        If the response is satisfactory, say "RESPONSE_SATISFACTORY".
        """
        
        try:
            # Use synchronous completion
            reflection = Settings.llm.complete(reflection_prompt)
            state["reflection_feedback"] = str(reflection)
            state["reflection_state"] = ReflectionState.REFLECTING.value
        except Exception as e:
            print(f"❌ Error in reflection: {e}")
            state["reflection_feedback"] = "RESPONSE_SATISFACTORY"  # Skip reflection on error
            
        return state
    
    def _refine_response_node(self, state: Dict) -> Dict:
        """Refine response based on reflection feedback"""
        current_response = state.get("refined_response") or state.get("initial_response", "")
        query = state.get("query", "")
        reflection_feedback = state.get("reflection_feedback", "")
        iteration_count = state.get("iteration_count", 0)
        
        refinement_prompt = f"""
        Original Query: {query}
        Current Response: {current_response}
        Reflection Feedback: {reflection_feedback}
        
        Based on the feedback, provide an improved response that addresses the identified issues.
        """
        
        try:
            # Use synchronous completion
            refined_response = Settings.llm.complete(refinement_prompt)
            state["refined_response"] = str(refined_response)
            state["reflection_state"] = ReflectionState.REFINED.value
            state["iteration_count"] = iteration_count + 1
        except Exception as e:
            print(f"❌ Error refining response: {e}")
            # Keep the current response if refinement fails
        
        return state
    
    def _should_reflect(self, state: Dict) -> str:
        """Determine if response should be reflected upon"""
        reflection_state = state.get("reflection_state", ReflectionState.INITIAL.value)
        if reflection_state == ReflectionState.INITIAL.value:
            return "reflect"
        return "end"
    
    def _should_continue_reflection(self, state: Dict) -> str:
        """Determine if reflection should continue"""
        iteration_count = state.get("iteration_count", 0)
        max_iterations = state.get("max_iterations", 3)
        reflection_feedback = state.get("reflection_feedback", "")
        
        if (iteration_count < max_iterations and 
            "RESPONSE_SATISFACTORY" not in reflection_feedback):
            return "continue"
        
        final_response = state.get("refined_response") or state.get("initial_response", "")
        state["final_response"] = final_response
        state["reflection_state"] = ReflectionState.FINAL.value
        return "end"
    
    async def query(self, user_query: str) -> Dict[str, Any]:
        """Execute RAG query with self-reflection"""
        initial_state = {
            "query": user_query,
            "table_schemas": [],
            "selected_tables": [],
            "sql_query": "",
            "query_results": [],
            "context_documents": [],
            "initial_response": "",
            "reflection_feedback": "",
            "refined_response": "",
            "final_response": "",
            "reflection_state": ReflectionState.INITIAL.value,
            "iteration_count": 0,
            "max_iterations": 3
        }
        
        config = {"configurable": {"thread_id": "rag_session"}}
        
        try:
            final_state = await self.workflow.ainvoke(initial_state, config)
            
            return {
                "query": user_query,
                "final_response": final_state.get("final_response", "No response generated"),
                "selected_tables": final_state.get("selected_tables", []),
                "sql_query": final_state.get("sql_query", ""),
                "reflection_iterations": final_state.get("iteration_count", 0),
                "reflection_feedback": final_state.get("reflection_feedback", "")
            }
        except Exception as e:
            print(f"❌ Error in query execution: {e}")
            return {
                "query": user_query,
                "final_response": f"I apologize, but I encountered an error while processing your query: {str(e)}",
                "selected_tables": [],
                "sql_query": "",
                "reflection_iterations": 0,
                "reflection_feedback": ""
            }


# Usage Example with better error handling
async def main():
    try:
        # Load environment variables
        load_dotenv()
        
        # Table descriptions for better context
        table_descriptions = {
            "users": "User account information and details",
            "resume": "Resume data including extracted information and metadata",
            "job_description": "Job posting descriptions and requirements",
        }
        
        print("🚀 Initializing PostgreSQL RAG System...")
        
        # Initialize RAG system (will use environment variables)
        rag_system = PostgreSQLRAGSystem(
            table_descriptions=table_descriptions
        )
        
        print("✅ RAG System initialized successfully!")
        
        # Example queries
        queries = [
            "list is the one most recent resume extracted details?",
        ]
        
        for query in queries:
            print(f"\n{'='*60}")
            print(f"🔍 Query: {query}")
            print('='*60)
            
            result = await rag_system.query(query)
            
            print(f"📊 Selected Tables: {result['selected_tables']}")
            print(f"🔍 SQL Query: {result['sql_query']}")
            print(f"🔄 Reflection Iterations: {result['reflection_iterations']}")
            print(f"\n💡 Final Response:\n{result['final_response']}")
            
            if result['reflection_feedback']:
                print(f"\n🤔 Reflection Feedback:\n{result['reflection_feedback']}")
    
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        print("\n🔧 Troubleshooting steps:")
        print("1. Check your .env file contains all required variables")
        print("2. Verify your Azure OpenAI deployment names")
        print("3. Ensure your database connection is working")
        print("4. Check that your embedding deployment is active")


if __name__ == "__main__":
    asyncio.run(main())