import os
import logging
from dotenv import load_dotenv
from llama_index.core import Settings
from llama_index.llms.azure_openai import AzureOpenAI
from neo4j import GraphDatabase
from pathlib import Path

# Load environment variables - try multiple paths
def load_env_variables():
    """Try to load .env from multiple possible locations"""
    possible_paths = [
        Path(__file__).resolve().parent / ".env",  # Same directory
        Path(__file__).resolve().parent.parent / ".env",  # Parent directory
        Path.cwd() / ".env",  # Current working directory
        ".env"  # Relative to execution
    ]
    
    for env_path in possible_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Loaded .env from: {env_path}")
            return True
    
    print("❌ No .env file found in expected locations")
    return False

# Load environment variables FIRST
load_env_variables()

logging.basicConfig(level=logging.INFO)


class Neo4jQueryEngine:

    @staticmethod
    def setup_llm():
        """Configure Azure OpenAI LLM with proper validation"""
        
        # Debug: Print all environment variables (masked)
        azure_key = os.getenv("AZURE_OPENAI_KEY")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        azure_version = os.getenv("AZURE_OPENAI_VERSION")
        
        print(f"🔍 AZURE_OPENAI_KEY: {azure_key[:8] + '...' if azure_key and len(azure_key) > 8 else 'NOT SET'}")
        print(f"🔍 AZURE_OPENAI_ENDPOINT: {azure_endpoint}")
        print(f"🔍 AZURE_OPENAI_DEPLOYMENT: {azure_deployment}")
        print(f"🔍 AZURE_OPENAI_VERSION: {azure_version}")
        
        # Validate required environment variables
        if not azure_key:
            raise ValueError("❌ AZURE_OPENAI_KEY is not set")
        if not azure_endpoint:
            raise ValueError("❌ AZURE_OPENAI_ENDPOINT is not set")
        if not azure_deployment:
            raise ValueError("❌ AZURE_OPENAI_DEPLOYMENT is not set")
        if not azure_version:
            raise ValueError("❌ AZURE_OPENAI_VERSION is not set")
        
        # Ensure endpoint has proper format
        if not azure_endpoint.startswith('https://'):
            azure_endpoint = f"https://{azure_endpoint}"
        if not azure_endpoint.endswith('/'):
            azure_endpoint = f"{azure_endpoint}/"
            
        print(f"🔧 Using Azure endpoint: {azure_endpoint}")
        
        try:
            # Create Azure OpenAI instance with explicit parameters
            azure_llm = AzureOpenAI(
                model="gpt-4o-mini",
                deployment_name=azure_deployment,
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_version,
                temperature=0.1,  # Add explicit temperature
            )
            
            # Set the LLM in Settings
            Settings.llm = azure_llm
            
            logging.info("✅ Azure OpenAI LLM configured successfully")
            
            # Test the connection with a simple prompt
            print("🧪 Testing Azure OpenAI connection...")
            test_response = azure_llm.complete("Hello, this is a test.")
            print(f"✅ Connection test successful: {test_response.text[:50]}...")
            
            return azure_llm
            
        except Exception as e:
            logging.error(f"❌ Failed to configure Azure OpenAI: {str(e)}")
            print(f"❌ Error details: {e}")
            raise

    def __init__(self):
        # First setup the LLM
        print("🚀 Setting up Azure OpenAI LLM...")
        self.setup_llm()
        
        # Validate Neo4j environment variables
        neo4j_uri = os.getenv("NEO4J_URI")
        neo4j_username = os.getenv("NEO4J_USERNAME")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")  # Default to 'neo4j'
        
        print(f"🔍 NEO4J_URI: {neo4j_uri}")
        print(f"🔍 NEO4J_USERNAME: {neo4j_username}")
        print(f"🔍 NEO4J_PASSWORD: {'*' * len(neo4j_password) if neo4j_password else 'NOT SET'}")
        print(f"🔍 NEO4J_DATABASE: {neo4j_database}")
        
        if not all([neo4j_uri, neo4j_username, neo4j_password]):
            raise ValueError("❌ Missing Neo4j connection parameters")
        
        try:
            self.driver = GraphDatabase.driver(
                neo4j_uri,
                auth=(neo4j_username, neo4j_password)
            )
            # Test the connection
            with self.driver.session(database=neo4j_database) as session:
                session.run("RETURN 1")
            print("✅ Neo4j connection successful")
            
        except Exception as e:
            logging.error(f"❌ Failed to connect to Neo4j: {str(e)}")
            raise
        
        self.llm = Settings.llm

    def close(self):
        if hasattr(self, 'driver'):
            self.driver.close()

    def get_schema(self):
        """Return fixed Neo4j schema"""
        return """
(:Patient {
    name: STRING,
    age: INTEGER,
    gender: STRING,
    blood_type: STRING
})

(:Admission {
    admission_date: DATE,
    discharge_date: DATE or NULL,
    admission_type: STRING,
    billing_amount: FLOAT,
    room_number: STRING,
    test_results: STRING
})

(:Hospital {
    name: STRING
})

(:Doctor {
    name: STRING
})

(:InsuranceProvider {
    name: STRING
})

(:MedicalCondition {
    name: STRING
})

(:Medication {
    name: STRING
})

# Relationships

(:Patient)-[:HAS_ADMISSION]->(:Admission)
(:Admission)-[:AT_HOSPITAL]->(:Hospital)
(:Admission)-[:TREATED_BY]->(:Doctor)
(:Admission)-[:INSURED_BY]->(:InsuranceProvider)
(:Admission)-[:HAS_CONDITION]->(:MedicalCondition)
(:Admission)-[:TAKES_MEDICATION]->(:Medication)
"""

    def execute_cypher(self, cypher_query):
        """Execute Cypher query on Neo4j"""
        try:
            database = os.getenv("NEO4J_DATABASE", "neo4j")
            with self.driver.session(database=database) as session:
                result = session.run(cypher_query)
                return [record.data() for record in result]
        except Exception as e:
            logging.error(f"❌ Error executing Cypher query: {str(e)}")
            return f"❌ Error executing query: {str(e)}"

    def natural_language_to_cypher(self, question):
        """Convert natural language question to Cypher query using Azure OpenAI"""
        schema = self.get_schema()

        prompt = f"""
You are a Neo4j Cypher query expert. Convert the following natural language question into a Cypher query.

Database Schema:
{schema}

Question: {question}

Rules:
1. Return ONLY the Cypher query, no explanation
2. Use LIMIT 10 for queries that might return many results
3. Make sure the query is syntactically correct
4. Use MATCH, RETURN, WHERE clauses appropriately

Cypher Query:
"""

        try:
            # Use the Azure OpenAI LLM directly
            response = self.llm.complete(prompt)
            cypher_query = response.text.strip()

            # Clean up code block format
            if "```" in cypher_query:
                cypher_query = cypher_query.split("```")[1]
                cypher_query = cypher_query.replace("cypher", "").replace("CYPHER", "").strip()

            return cypher_query.strip()
            
        except Exception as e:
            logging.error(f"❌ Error generating Cypher query: {str(e)}")
            raise

    def query(self, question):
        """Main query method"""
        print(f"🤖 LLM Type: {type(self.llm)}")
        print(f"🔧 LLM Model: {getattr(self.llm, 'model', 'Unknown')}")
        
        logging.info("🧠 Converting question to Cypher...")
        try:
            cypher_query = self.natural_language_to_cypher(question)
            logging.info(f"📝 Generated Cypher: {cypher_query}")

            logging.info("🚀 Executing query...")
            results = self.execute_cypher(cypher_query)

            if isinstance(results, str):  # Error case
                return results

            # Format results using LLM
            format_prompt = f"""
Question: {question}
Cypher Query: {cypher_query}
Raw Results: {results}

Please provide a clear, human-readable answer to the original question based on these results.
If there are no results, say so clearly.
"""

            formatted_response = self.llm.complete(format_prompt)
            return formatted_response.text
            
        except Exception as e:
            logging.error(f"❌ Error in query method: {str(e)}")
            return f"❌ Error processing query: {str(e)}"


# Example usage and testing
if __name__ == "__main__":
    try:
        print("🚀 Initializing Neo4j Query Engine...")
        engine = Neo4jQueryEngine()
        
        # Test query
        test_question = "How many patients are there?"
        print(f"\n🔍 Testing with question: {test_question}")
        result = engine.query(test_question)
        print(f"📋 Result: {result}")
        
        engine.close()
        print("✅ Test completed successfully")
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")