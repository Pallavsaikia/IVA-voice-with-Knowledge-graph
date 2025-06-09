# 🧠 Neo4j-Powered Knowledge Graph with LlamaIndex RAG, LangGraph Agents & Real-Time Voice Bot

A scalable, intelligent LLM-based system combining **Neo4j**, **LlamaIndex**, **LangGraph**, and a **FastAPI voice bot** for real-time knowledge retrieval and conversation from voice input.

---

## Preview

![System Architecture](docs/ui.png)

## ✅ Project Summary

- ✅ Created **Knowledge Graph** in Neo4j to represent domain knowledge.
- ✅ Developed a **RAG agent** to query the KG using natural language via LlamaIndex.
- ✅ Implemented **WebSocket-based call system**, where the **bot joins** an audio channel upon trigger (not directly called).
- ✅ Built a **real-time audio interface** using browser and FastAPI.
- ✅ Added **speech-to-text transcription** using Whisper.
- ✅ Integrated **silence detection** and **noise filtering** to prevent unnecessary responses.
- ✅ Bot **decodes user speech**, queries the graph, and **responds intelligently** using LLMs.

---

## 🧱 Tech Stack

| Component         | Role                                                  |
|-------------------|-------------------------------------------------------|
| **Neo4j**         | Structured graph database                             |
| **LlamaIndex**    | Graph-aware RAG (retrieval-augmented generation)      |
| **LangGraph**     | Multi-agent orchestration and reasoning logic         |
| **OpenAI / Azure**| Backend LLMs like GPT-4 / GPT-4o / GPT-4-turbo        |
| **FastAPI**       | WebSocket server, API endpoints                       |
| **Whisper**       | Real-time transcription of user audio                 |
| **HTML + JS**     | Frontend with audio streaming support                 |

---

## 🗂️ Project Structure

```bash
.
├── audio/                        # Audio helpers or processing
├── data/                         # Datasets (e.g., healthcare_dataset.csv)
├── interface/
│   └── websocket.py
├── rag/   
│   └── neo4j.py                  # RAG logic and agents
├── static/
│   └── index.html                # Web interface for call
├── transcription/
│   └── transcriber.py           # Transcribes and filters incoming audio
├── utils/
│   └── logger.py           
├── .env                          # Env config (keys, URIs)
├── .gitignore
├── audio.py                      # Handles audio input/output
├── bot.py                        # Bot logic (join, listen, respond)
├── config.py                     # App-level configs
├── main.py                       # FastAPI app entry point
├── README.md
└── upload_data.py                # Load CSV data to Neo4j

```

## Run

This guide contains all the required steps to run the full voice-interactive system powered by Neo4j, LlamaIndex, LangGraph, and Whisper.

---

## 🛠️ Steps to Run

### 1. Create `.env` File

Create a `.env` file in the bot root with the details in .env-example

### 1.1. Move data to neo4j
```bash
cd bot
python upload_data.py
```
### 2. Run socket server
```bash
cd server
go run main.go
```
### 3. Run bot
```bash
cd bot
uvicorn bot:app --reload --host 0.0.0.0 --port 9000
```


### 4. Run user server
```bash
cd bot
uvicorn main:app --reload --host 0.0.0.0 --port 7000
```


