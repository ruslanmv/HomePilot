# HomePilot AI Agents & Tool Servers

## What Are AI Agents in HomePilot?

Think of AI agents like **smart assistants that live inside HomePilot**. Just like how Microsoft Word has a spell checker that works automatically in the background, HomePilot has a set of built-in AI helpers that can search your documents, help you make decisions, write reports, and even look things up on the internet.

You don't need to install anything extra. When you start HomePilot, all of these helpers start automatically and are ready to use.

---

## What Comes Built In?

HomePilot includes **5 tool servers** (think of them like specialized apps) and **2 AI assistants** that can use those tools:

### Tool Servers (The "Apps")

| Tool Server | What It Does |
| :--- | :--- |
| **Personal Assistant** | Helps with everyday planning. Search your notes, plan your day. Like a smart planner. |
| **Knowledge** | Searches your workspace documents, finds answers, and summarizes projects. Like a research librarian. |
| **Decision Copilot** | Helps you make decisions. Shows options, analyzes risks, and recommends next steps. Like a strategy advisor. |
| **Executive Briefing** | Creates daily and weekly summaries of what happened and what changed. Like a news digest for your projects. |
| **Web Search** | Looks things up on the internet for you. Works without any account or API key for home users. |

### AI Assistants (The "People")

| Assistant | What It Does |
| :--- | :--- |
| **Everyday Assistant** | A friendly helper that summarizes information and helps you plan. It only reads and suggests — it never makes changes on its own. |
| **Chief of Staff** | A more advanced assistant that gathers facts, organizes options, and creates briefings. It always asks for your approval before taking any action. |

---

## How Do I Use Them?

### Step 1: Start HomePilot

When you start HomePilot normally, all the tool servers and AI assistants start automatically in the background. There is nothing extra to do.

### Step 2: Create an Agent Project

1. Open HomePilot in your browser
2. Go to **Projects** in the sidebar
3. Click **New Project** and choose **Agent Project**
4. A guided wizard walks you through 4 simple steps:
   - **Details** — Give your agent a name and describe what it should do
   - **Access & Connections** — Pick which tools your agent can use (Knowledge, Decision, Web Search, etc.)
   - **Knowledge** — Choose what information your agent can access
   - **Review** — Check everything and create your agent

### Step 3: Talk to Your Agent

Once created, your agent can use the tools you gave it. For example, if you gave it Web Search and Knowledge tools, you can ask:
- "What are the latest trends in renewable energy?" (uses Web Search)
- "Summarize the Q4 report from our documents" (uses Knowledge)
- "What are our options for reducing shipping costs?" (uses Decision Copilot)

---

## What Is MCP Context Forge?

**MCP Context Forge** is the central hub that connects everything together. Think of it like the **Windows Control Panel** — but instead of managing printers and displays, it manages all your AI tools and assistants.

### What It Does

- **Discovers tools** — Keeps a catalog of every tool server that is running, so agents know what is available
- **Connects agents to tools** — When an agent needs to search the web or look up a document, Context Forge routes the request to the right tool server
- **Manages permissions** — Controls which tools are available and which agents can use them

### Do I Need to Configure It?

**No.** Context Forge starts automatically and configures itself. All the built-in tool servers register themselves when HomePilot starts. You only need to touch Context Forge settings if you want to add your own custom tools (see below).

---

## Web Search: Home vs Enterprise

HomePilot includes a web search tool that works differently depending on your setup:

### Home Users (Default)

- Uses **SearXNG**, a private search engine that runs on your own computer
- **No account or API key needed** — completely free and private
- Searches multiple search engines (Google, Bing, DuckDuckGo) without tracking you
- To start it: open a terminal and run the SearXNG container (a one-time setup)

### Enterprise Users

- Uses **Tavily**, a commercial search service designed for AI applications
- Requires an API key (sign up at tavily.com)
- Higher quality results optimized for AI research tasks
- To switch: set your Tavily API key in the environment settings

Both options provide the exact same features to your agents. The only difference is where the search results come from.

---

## How to Add a New Tool Server

Want to give your agents a new ability? Here is how to add a custom tool server to HomePilot:

### Step 1: Write the Tool Server

Create a new file inside the tool servers folder. Your tool server is a small application that does one thing well — for example, checking the weather, reading emails, or querying a database.

Each tool server needs:
- A **name** — like "Weather Checker" or "Email Reader"
- One or more **tools** — specific actions it can perform (e.g., "get forecast", "list unread emails")
- A **description** for each tool — so the AI agent knows when to use it

HomePilot includes a shared template that handles all the technical details. You just define what your tools do.

### Step 2: Register It with Context Forge

Add your new tool server to the gateway templates file so Context Forge knows about it. This is like adding a new printer to Windows — you tell the system where it is and what it can do.

### Step 3: Add It to a Suite

Suites are like **preset configurations**. HomePilot has two built-in suites:

- **Home Suite** — Tools selected for personal use (planning, knowledge, web search)
- **Pro Suite** — All tools including decision-making and executive briefings

Add your new tool to whichever suite makes sense, and it will appear as an option in the agent creation wizard.

### Step 4: Start It

Add your tool server to the startup script so it launches automatically with HomePilot. Once added, it will appear in the wizard the next time you create an agent project.

---

## Managing Your Tool Servers

### Checking Server Health

All tool servers have a built-in health check. When HomePilot starts, it automatically verifies that all 7 services (5 tool servers + 2 AI assistants) are running and healthy. You will see a status message in the terminal.

### Stopping and Restarting

- **Stop everything:** Use the stop command in your terminal. All tool servers shut down together with HomePilot.
- **Restart just the tool servers:** You can restart the AI tool servers independently without restarting the entire application.

### Viewing Available Tools

- Open the **Context Forge admin panel** in your browser to see all registered tools, agents, and their status
- Use the **Agent Creation Wizard** in HomePilot to browse available tools in a user-friendly interface

---

## Quick Reference

### Built-in Services

| Service | Type | What It Does |
| :--- | :--- | :--- |
| Personal Assistant | Tool Server | Daily planning and personal search |
| Knowledge | Tool Server | Document search, Q&A, project summaries |
| Decision Copilot | Tool Server | Options analysis, risk assessment, recommendations |
| Executive Briefing | Tool Server | Daily/weekly summaries and change digests |
| Web Search | Tool Server | Internet search and web page reading |
| Everyday Assistant | AI Assistant | Friendly helper (read-only, advisory) |
| Chief of Staff | AI Assistant | Advanced orchestrator (asks before acting) |

### Key Concepts

| Term | What It Means |
| :--- | :--- |
| **Tool Server** | A small app that gives AI agents a specific ability (like searching or summarizing) |
| **AI Assistant (A2A Agent)** | A smart coordinator that uses multiple tools to complete complex tasks |
| **MCP Context Forge** | The central hub that connects agents to tools (like a switchboard) |
| **Suite** | A preset bundle of tools designed for a specific use case (Home or Pro) |
| **Virtual Server** | A named group of related tools (e.g., "Web Research" groups search + fetch together) |

---

## Frequently Asked Questions

**Do I need to be technical to use this?**
No. Everything starts automatically. Just create an agent project through the wizard and pick the tools you want.

**Is my data private?**
Yes. All tool servers run on your own computer. Nothing is sent to external services unless you choose to use Tavily for web search.

**Can I use this without internet?**
Yes, for everything except Web Search. The Knowledge, Decision, Briefing, and Personal Assistant tools all work completely offline.

**What happens if a tool server crashes?**
The other tools keep working. You can restart just the tool servers without affecting the rest of HomePilot.

**Can I add tools from other sources?**
Yes. MCP Context Forge supports connecting to any compatible tool server. The community has 20+ additional servers available at the [MCP Context Forge repository](https://github.com/ruslanmv/mcp-context-forge).
