import pandas as pd
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE")

df = pd.read_csv("data/healthcare_dataset.csv")
df["Date of Admission"] = pd.to_datetime(df["Date of Admission"], dayfirst=True, errors="coerce").dt.strftime('%Y-%m-%d')
df["Discharge Date"] = pd.to_datetime(df["Discharge Date"], dayfirst=True, errors="coerce").dt.strftime('%Y-%m-%d')
driver = GraphDatabase.driver(uri, auth=(user, password))

def load_row(tx, row):
    tx.run("""
        MERGE (p:Patient {name: $name})
        SET p.age = $age, p.gender = $gender, p.blood_type = $blood_type

        CREATE (a:Admission {
            admission_date: date($admission_date),
            discharge_date: CASE WHEN $discharge_date <> '' THEN date($discharge_date) ELSE NULL END,
            admission_type: $admission_type,
            billing_amount: $billing_amount,
            room_number: $room_number,
            test_results: $test_results
        })

        MERGE (h:Hospital {name: $hospital})
        MERGE (d:Doctor {name: $doctor})
        MERGE (i:InsuranceProvider {name: $insurance})
        MERGE (c:MedicalCondition {name: $condition})
        MERGE (m:Medication {name: $medication})

        MERGE (p)-[:HAS_ADMISSION]->(a)
        MERGE (a)-[:AT_HOSPITAL]->(h)
        MERGE (a)-[:TREATED_BY]->(d)
        MERGE (a)-[:INSURED_BY]->(i)
        MERGE (a)-[:HAS_CONDITION]->(c)
        MERGE (a)-[:TAKES_MEDICATION]->(m)
    """, {
        "name": row['Name'],
        "age": int(row['Age']),
        "gender": row['Gender'],
        "blood_type": row['Blood Type'],
        "admission_date": row['Date of Admission'],
        "discharge_date": row['Discharge Date'],
        "admission_type": row['Admission Type'],
        "billing_amount": float(row['Billing Amount']),
        "room_number": str(row['Room Number']),
        "test_results": row['Test Results'],
        "doctor": row['Doctor'],
        "hospital": row['Hospital'],
        "insurance": row['Insurance Provider'],
        "condition": row['Medical Condition'],
        "medication": row['Medication']
    })


with driver.session(database=database) as session:
    for _, row in df.iterrows():
        session.execute_write(load_row, row)

print("✅ Data imported into Neo4j.")
