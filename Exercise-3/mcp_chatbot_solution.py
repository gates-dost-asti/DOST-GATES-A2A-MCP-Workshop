
from utils import is_threat
from openai import OpenAI
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from datetime import datetime
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
import asyncio
#import nest_asyncio
import json
from pathlib import Path
import sys

#nest_asyncio.apply()

load_dotenv()

client = OpenAI(
    api_key=os.getenv("BEDROCK_KEY"),
    base_url="https://bedrock-mantle.us-east-1.api.aws/openai/v1"
)

class WorkflowChoice(BaseModel):
    choice: Optional[Literal[
        "txt2sql_workflow",
        "rag_workflow",
        "waypoints_workflow",
        "nearest_labs_workflow",
        "analysis_workflow"        
    ]] = Field(
        default = None,
        description = """`txt2sql_workflow`: the user is asking for information on the location of laboratories and agencies as well as the services that they offer.
        `waypoints_workflow`: the user is asking about how to go to a particular agency from a certain location.
        `rag_workflow`: the user is asking for client steps, processes, requirements, or information on how to avail of a particular service in an agency
        `nearest_labs_workflow`: the user is asking for nearest laboratories and/or the services that they offer given a reference location
        `analysis_workflow`: the user is asking about hotspot and service area analysis questions (data is for provincial level analysis only)
        """
    )
    fallback: Optional[str] = Field(default=None, description="Fallback response if the user's query does not fall in any of the given choices")

system_prompt = """Your task is to choose the appropriate workflow depending on the user's intent.
`txt2sql_workflow`: the user is asking for information on the location of laboratories and agencies as well as the services that they offer.
`waypoints_workflow`: the user is asking about how to go to a particular agency from a certain location.
`rag_workflow`: the user is asking for client steps, processes, requirements, or information on how to avail of a particular service in an agency
`nearest_labs_workflow`: the user is asking for nearest laboratories and/or the services that they offer given a reference location
`analysis_workflow`: the user is asking about hotspot and service area analysis questions

For more context, these are some of the queries that can be processed by the workflows:
`What services does DOST-ITDI offer?`
`What do I need to prepare for pipe stiffness test for pvc in DOST-ITDI`
`How do I get to DOST-ASTI from SMDC Light Residences`
`10 nearest laboratories to SMDC Light Residences that offer coliform count`
`Which provinces are classified as potentially underserved`

If the user's intent is does not fall in any of the workflows, return a fallback reply highlighting allowed questions.
"""

class MCP_ChatBot:

    def __init__(self):
        self.session: ClientSession = None
        self.available_tools: List[dict] = []

    async def get_intent(self, user_query):
        response = client.responses.parse(
            model="openai.gpt-5.6-luna",
            input = [
                {
                    "role":"system",
                    "content": system_prompt
                },
                {
                    "role":"user",
                    "content": user_query
                }
            ],
            text_format = WorkflowChoice
        )
        return response.output_parsed

    async def answer_query(self, user_query: str):

        _is_threat, errors = is_threat(user_query)

        if _is_threat:
            text = "I'm sorry, but I couldn't process your request as it was potentially unsafe. If you think this was a mistake, please try rephrasing your prompt or providing more context so I can better understand your request."
            html = None
            result = {
                "text": text,
                "html": html
            }
            return result

        response = await self.get_intent(user_query)
        workflow = response.choice
        fallback = response.fallback

        if not workflow:

            result = {
                "text": fallback or "I could not determine the appropriate workflow.",
                "html": None
            }   
            return result

        server_script = (Path(__file__).resolve().parent / "../onelab_server/onelab_server.py").resolve()
        server_params = StdioServerParameters(
            command=sys.executable,  # Executable
            args=[str(server_script)],  # Optional command line arguments
            env=None,  # Optional environment variables
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the connection
                await session.initialize()

                # List available tools
                tool_response = await session.list_tools()

                tools = tool_response.tools
                #print("\nConnected to server with tools:", [tool.name for tool in tools])

                self.available_tools = [{
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                } for tool in tools]

                if workflow:
                    response = await session.call_tool(workflow, arguments = {"user_query":user_query})
                    #result, html = response.structuredContent["result"]
                    if response.isError:
                        #print(response.content[0].text)

                        result = {
                            "text": response.content[0].text,
                            "html": None
                        }
                        return result

                    if response.structuredContent is not None:
                        res, html = response.structuredContent["result"]
                        result = {
                            "text": res,
                            "html": html
                        }
                        return result
                    else:
                        # Fallback to TextContent
                        texts = [c.text for c in response.content]

                        res = texts[0] if len(texts) > 0 else None
                        html = texts[1] if len(texts) > 1 else None

                        result = {
                            "text": res,
                            "html": html
                        }
                        return result

                else:
                    result = {
                        "text": "Process failed",
                        "html": None
                    }     
                    return result
        
    async def chat(self):
        if datetime.now().hour < 12:
            time = "morning"
        elif datetime.now().hour >= 12:
            time = "afternoon"
        else:
            time = "evening"
        print(f"\nOneLab Agent:\nGood {time}! How may I assist you?")

        while True:

            user_query = input("Enter your query: ")
            print(f"\nUser:\n{user_query}")

            if user_query.lower() == "quit":
                break

            _is_threat, errors = is_threat(user_query)

            if _is_threat:
                print("\nOneLab Agent:\nI'm sorry, but I couldn't process your request as it was potentially unsafe. If you think this was a mistake, please try rephrasing your prompt or providing more context so I can better understand your request.")
                continue

            response = await self.get_intent(user_query)
            workflow = response.choice
            fallback = response.fallback

            if workflow:
                response = await self.session.call_tool(workflow, arguments = {"user_query":user_query})
                #result, html = response.structuredContent["result"]
                if response.isError:
                    print(response.content[0].text)
                    return

                if response.structuredContent is not None:
                    result, html = response.structuredContent["result"]
                else:
                    # Fallback to TextContent
                    texts = [c.text for c in response.content]

                    result = texts[0] if len(texts) > 0 else None
                    html = texts[1] if len(texts) > 1 else None
                print(f"\nOneLab Agent:\n{result}")
                if html:
                    print("---\nOpen `output.html` for the visualization.")
            elif fallback:
                print(f"\nOneLab Agent:\n{fallback}")

    async def connect_to_server_and_run(self):
        # Create server parameters for stdio connection
        server_params = StdioServerParameters(
            command="uv",  # Executable
            args=["run", "../onelab_server/onelab_server.py"],  # Optional command line arguments
            env=None,  # Optional environment variables
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                self.session = session
                # Initialize the connection
                await session.initialize()

                # List available tools
                response = await session.list_tools()

                tools = response.tools
                print("\nConnected to server with tools:", [tool.name for tool in tools])

                self.available_tools = [{
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                } for tool in response.tools]

                await self.chat()

async def main():
    chatbot = MCP_ChatBot()
    await chatbot.connect_to_server_and_run()


if __name__ == "__main__":
    asyncio.run(main())
