import os
import uvicorn
import uuid
import json

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    Part,
    TextPart,
    TaskArtifactUpdateEvent
)
from a2a.utils import new_agent_text_message

from mcp_chatbot import MCP_ChatBot


class OneLabAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.agent = MCP_ChatBot()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        prompt = context.get_user_input()
        try:
            result = await self.agent.answer_query(prompt)
            text = result["text"]
            html = result["html"]

            response_dict = {
                "text": text,
                "html": html
            }

            response = json.dumps(response_dict)

            message = new_agent_text_message(response)
            await event_queue.enqueue_event(message)

        except Exception as exc:
            response = {
                "text": f"Unable to process the request: {exc}",
                "html": None
            }
            await event_queue.enqueue_event(
                new_agent_text_message(
                    json.dumps(response)
                )
            )
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        pass

def main() -> None:
    print(f"Running OneLab Agent")
    PORT = 9999
    HOST = "localhost"

    skill = AgentSkill(
        id="onelab_assistance",
        name="OneLab Assistance",
        description="Provides information about OneLab laboratories, services, requirements for testing, directions, nearby laboratories, and service-area analysis (provincial level)",
        tags=["onelab", "laboratories", "laboratory services", "directions", "laboratory test requirements", "provincial level service-area analysis"],
        examples=[
            "What services does itdi and xprt offer",
            "Show me the laboratories in NCR",
            "What laboratories in laguna offer ash content test",
            "Laboratories in quezon city",
            "what is the process for mosquito larvicidal test in itdi",
            "administrative process in itdi for arsenic test for distilled water",
            "what do i need to prepare for pipe stiffness test for pvc in itdi ", 
            "how do i get to asti from smdc light residences",
            "directions to itdi from mall of asia",
            "10 nearest laboratories to SMDC light residences that offer coliform count",  
            "Where are onelab agencies concentrated",
            "Which provinces have the most onelab services",
            "which provinces have the broadest range of tests",
            "which provinces have no local onelab presence",
            "which provinces are classified as potentially underserved",
            "Can you give a numerical summary of the service area classification"
        ],
    )

    agent_card = AgentCard(
        name="OneLabAgent",
        description="OneLab laboratory and services information agent.",
        url=f"http://{HOST}:{PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text", "text/html"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=OneLabAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)


if __name__ == '__main__':
    main()

