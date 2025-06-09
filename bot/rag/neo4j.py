import os
import logging
from dotenv import load_dotenv
from llama_index.core import Settings
from llama_index.llms.azure_openai import AzureOpenAI
from neo4j import GraphDatabase
from pathlib import Path
# Load environment variables from one level above
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv()

logging.basicConfig(level=logging.INFO)


class Neo4jQueryEngine:

    @staticmethod
    def setup_llm():
        """Configure Azure OpenAI LLM"""
        Settings.llm = AzureOpenAI(
            model="gpt-4o-mini",
            deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_VERSION"),
        )
        logging.info("✅ Azure OpenAI LLM configured")

    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
        )
        self.llm = Settings.llm

    def close(self):
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
            with self.driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
                result = session.run(cypher_query)
                return [record.data() for record in result]
        except Exception as e:
            return f"❌ Error executing query: {str(e)}"

    def natural_language_to_cypher(self, question):
        """Convert natural language question to Cypher query using LLM"""
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

        response = self.llm.complete(prompt)
        cypher_query = response.text.strip()

        # Clean up code block format
        if "```" in cypher_query:
            cypher_query = cypher_query.split("```")[1]
            cypher_query = cypher_query.replace("cypher", "").strip()

        return cypher_query.strip()

    def query(self, question):
        """Main query method"""
        logging.info("🧠 Converting question to Cypher...")
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


def main():
    """Main loop for querying"""

    Neo4jQueryEngine.setup_llm()
    query_engine = Neo4jQueryEngine()

    print("\n=== Neo4j Query System Ready ===")
    print("Type 'quit' to exit")
    print("Example queries:")
    print("- 'What nodes are in the database?'")
    print("- 'Show me all relationships'")
    print("- 'Count all nodes'")

    try:
        while True:
            user_query = input("\nEnter your query: ").strip()

            if user_query.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not user_query:
                continue

            try:
                print(f"\nProcessing: {user_query}")
                response = query_engine.query(user_query)
                print(f"\nResponse:\n{response}")

            except Exception as e:
                print(f"Error: {str(e)}")

    finally:
        query_engine.close()


if __name__ == "__main__":
    main()
