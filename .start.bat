@echo off
cd /d D:\N2X\knowledge-chatbot
call venv\Scripts\activate
start http://127.0.0.1:8000
uvicorn app.main:app --reload