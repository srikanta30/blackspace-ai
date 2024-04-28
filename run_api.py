import json
import os
from typing import List

from io import BytesIO

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import PyPDF2

from server.api import BlackSpaceAPI

# Load environment variables
load_dotenv()

# Access environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CORS_ORIGINS = ["http://localhost:3000"]
CORS_METHODS = ["GET", "POST"]

# Initialize FastAPI app
app = FastAPI()

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=CORS_METHODS,
    allow_headers=["*"],
)

from fastapi import Header, HTTPException, Depends

class AuthenticatedResponse(BaseModel):
    message: str

def get_auth_key(authorization: str = Header(...)) -> None:
    auth_key = os.getenv("AUTH_KEY")
    if not auth_key:
        raise HTTPException(status_code=500, detail="AUTH_KEY not configured")
    expected_header = f"Bearer {auth_key}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/")
async def say_hello():
    return {"message": "Hello World"}


class MessageList(BaseModel):
    session_id: str
    human_say: str


sessions = {}


@app.get("/botname", response_model=None)
async def get_bot_name(authorization: str = Header(...)):
    load_dotenv()
    get_auth_key(authorization)
    sales_api = BlackSpaceAPI(
        config_path=os.getenv("CONFIG_PATH"),
        product_catalog=os.getenv(
            "PRODUCT_CATALOG"
        ),
        verbose=True,
        model_name=os.getenv("GPT_MODEL", "gpt-3.5-turbo-0613"),
    )
    name = sales_api.sales_agent.salesperson_name
    return {"name": name, "model": sales_api.sales_agent.model_name}


@app.post("/chat")
async def chat_with_sales_agent(session_id: str = Body(...), human_say: str = Body(...), conversation_history: List[str] = Body(...), stream: bool = Query(False), authorization: str = Header(...), file: UploadFile = File(None)):
    sales_api = None
    get_auth_key(authorization)
    if session_id in sessions:
        print("Session is found!")
        sales_api = sessions[session_id]
        print(f"Are tools activated: {sales_api.sales_agent.use_tools}")
        print(f"Session id: {session_id}")
    else:
        print("Creating new session")
        sales_api = BlackSpaceAPI(
            config_path=os.getenv("CONFIG_PATH"),
            verbose=True,
            product_catalog=os.getenv(
                "PRODUCT_CATALOG"
            ),
            model_name=os.getenv("GPT_MODEL", "gpt-3.5-turbo-0613"),
            use_tools=os.getenv("USE_TOOLS_IN_API", "True").lower()
            in ["true", "1", "t"],
        )
        print(f"TOOLS?: {sales_api.sales_agent.use_tools}")
        sessions[session_id] = sales_api

    if file is not None:
        if not file.filename.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        file_content = await file.read()

        pdf_reader = PyPDF2.PdfFileReader(BytesIO(file_content))
        num_pages = pdf_reader.numPages
    extracted_text = ""

    for page_num in range(num_pages):
        page = pdf_reader.getPage(page_num)
        extracted_text += page.extractText()

    if stream:

        async def stream_response():
            stream_gen = sales_api.do_stream(conversation_history, human_say + extracted_text)
            async for message in stream_gen:
                data = {"token": message}
                yield json.dumps(data).encode("utf-8") + b"\n"

        return StreamingResponse(stream_response())
    else:
        response = await sales_api.do(human_say + extracted_text)
        return response


# Main entry point
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
