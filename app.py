from dotenv import load_dotenv

from agentmail import AgentMail, Message
from agentmail_toolkit.openai import AgentMailToolkit

from typing import Optional
from pydantic import BaseModel, Field
from agents import Agent, Runner

from flask import Flask, request, Response
import asyncio
from threading import Thread


load_dotenv()

client = AgentMail()

inbox = client.inboxes.create(
    display_name="AgentMail",
    username="connect",
    client_id="connect-demo-inbox",
)

client.webhooks.create(
    url="https://connect-demo.onrender.com/webhooks",
    inbox_ids=[inbox.inbox_id],
    event_types=["message.received"],
    client_id="connect-demo-webhook",
)

instructions = f"""
You are an email assistant. You will receive an email from a user and you will respond to it.

The user's email will introduce themselves with their interests and background. If they do not provide this infromation, respond by asking them for this information.

If the user's email does provide sufficient information, your task is to connect them with another user who has similar interests or background.

Do this by calling the list_threads tool to get a list of threads and then calling the get_thread tool to get the details of a thread to find a user who has similar interests or background.

Regardless of how similar the interests or background are, choose the one most similar user to connect the user with.

Once you have found a user who has similar interests or background, you will respond by introducing them and CCing their email address in the reply.

Respond with plain text in email format. Do not include any other text or formatting. In the email signature refer to yourself as "AgentMail".
"""

tools = [
    tool
    for tool in AgentMailToolkit().get_tools()
    if tool.name in ["list_threads", "get_thread"]
]


class AgentResponse(BaseModel):
    cc: Optional[str] = Field(description="The email address to CC in the reply.")
    body: str = Field(description="The plain text body of the reply.")


agent = Agent(
    name="Connect Agent",
    instructions=instructions,
    tools=tools,
    output_type=AgentResponse,
)

app = Flask(__name__)


@app.post("/webhooks")
def receive_webhook():
    Thread(target=process_webhook, args=(request.json,)).start()
    return Response(status=200)


def process_webhook(payload):
    message = Message(**payload["message"])

    if message.cc:
        print("Skipping message with CC:", message.cc)
        return

    try:
        thread = client.inboxes.threads.get(
            inbox_id=message.inbox_id, thread_id=message.thread_id
        )

        prompt = thread.model_dump_json()
        print("Prompt:\n\n", prompt, "\n")

        response: AgentResponse = asyncio.run(Runner.run(agent, prompt)).final_output
        print("Response:\n\n", response.model_dump_json(), "\n")

        client.inboxes.messages.reply(
            inbox_id=message.inbox_id,
            message_id=message.message_id,
            cc=response.cc,
            text=response.body,
        )
    except Exception as e:
        print("Error processing message:", e)

        client.inboxes.messages.reply(
            inbox_id=message.inbox_id,
            message_id=message.message_id,
            text=f"Hi,\n\nI'm sorry, there was an error processing your message: {str(e)}\n\nPlease try again later.\n\nBest,\nAgentMail",
        )


if __name__ == "__main__":
    print(f"Inbox: {inbox}\n")

    app.run()
