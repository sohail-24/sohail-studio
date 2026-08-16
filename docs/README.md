# Sohail Studio

> **A Local-First AI Engineering Workspace powered by Sohail-Agent-CLI**

---

# 🚀 Vision

Sohail Studio is **not another AI chatbot**.

It is a **visual engineering workspace** that allows developers to collaborate with AI while keeping full control over execution.

Instead of copying the functionality of ChatGPT, Cursor, or VS Code, Sohail Studio combines the best parts of each into a single engineering environment focused on **planning, building, debugging, and deploying software**.

The existing **Sohail-Agent-CLI** remains the engineering engine.

Sohail Studio is simply the visual layer.

Everything runs locally.

Everything is transparent.

Everything requires approval before execution.

---

# ✨ Philosophy

```
Think

   ↓

Plan

   ↓

Review

   ↓

Approve

   ↓

Execute

   ↓

Observe

   ↓

Learn

   ↓

Remember
```

The Studio never hides commands.

The Studio never silently modifies projects.

The engineer is always in control.

---

# 🎯 Goals

Sohail Studio is designed to become the daily workspace for software engineers.

Instead of switching between

* Terminal
* Browser
* Documentation
* AI Chat
* Docker Desktop
* Kubernetes Dashboard
* Git

everything should exist inside one application.

---

# 🏗 Architecture

```
Browser UI
      │
      ▼
 FastAPI Backend
      │
      ▼
  CLI Bridge
      │
      ▼
Sohail-Agent-CLI
      │
      ▼
 Local Terminal
      │
      ▼
 Workspace
```

The Studio never duplicates business logic.

The CLI remains the single source of engineering intelligence.

---

# 📁 Project Structure

```
dashboard/
    HTML
    CSS
    JavaScript

backend/
    FastAPI
    REST API
    WebSocket

core/
    CLI Bridge
    Session Store

terminal/
    PTY Bridge

workspace/
    Local Workspace

sessions/
    Session History

logs/
    Execution Logs

settings/
    Configuration
```

---

# 🧠 Main Interface

The interface is divided into five primary sections.

---

## ① 3D Engineering Knowledge Sphere

The upper-left panel contains a rotating engineering knowledge sphere.

Unlike a chat history, this becomes the visual memory of the workspace.

Examples of nodes

* Docker
* Kubernetes
* Terraform
* Python
* FastAPI
* React
* Redis
* PostgreSQL
* Git
* CI/CD
* Documentation
* Errors
* Sessions

Features

* Continuous rotation
* Mouse drag
* Zoom
* Click nodes
* Automatic relationships
* Workspace filtering

Every completed workflow becomes part of the engineering graph.

---

## ② AI Mentor

The left panel is not a chatbot.

It behaves like a senior Platform Engineer.

Examples

* Suggest next task
* Detect missing files
* Recommend Docker improvements
* Review Kubernetes manifests
* Explain architecture
* Suggest documentation
* Warn about security problems
* Recommend CI/CD improvements

The mentor guides the engineer rather than replacing them.

---

## ③ Workspace Canvas

This is where engineering actually happens.

The canvas displays

* Plans
* Generated files
* Architecture
* Documentation
* Preview
* Logs
* Markdown
* Diffs
* Timeline
* Memory

The Workspace should never feel like a chat window.

It should feel like an IDE.

---

## ④ Terminal

The terminal is powered by the existing PTY bridge.

Displays

* Commands
* Purpose
* Live output
* Exit code
* Execution time

Future improvements

* Floating terminal
* Split terminal
* Multiple sessions

---

## ⑤ Natural Language Command Bar

Users interact using plain English.

Example

```
Inspect project

Generate Dockerfile

Explain architecture

Generate Kubernetes

Review repository

Generate README

Fix Docker error

Deploy locally
```

Every request creates a plan.

Nothing executes automatically.

---

# 🤖 AI Provider System

Sohail Studio supports multiple AI providers while keeping the interface exactly the same.

Current Providers

✅ Ollama

Runs locally.

Default provider.

No internet required.

Optional Provider

✅ Google Gemini API

Configured using an API key.

Useful for larger reasoning tasks.

Future Providers

* OpenAI
* Claude
* DeepSeek
* Groq
* LM Studio

Switching providers never changes the UI.

Only the backend provider changes.

---

# 🔄 Provider Selection Logic

When the user sends a message

Example

```
Hello
```

The Studio checks

```
Is Ollama running?

YES

↓

Use Ollama.
```

Otherwise

```
Is Gemini configured?

YES

↓

Use Gemini.
```

Otherwise

```
Display

"No AI Provider Configured."
```

This allows the Studio to work offline whenever possible.

---

# 🔗 CLI Integration

Sohail Studio never replaces Sohail-Agent-CLI.

The Studio only orchestrates it.

Responsibilities

Studio

* Visual Interface
* Plans
* Sessions
* Terminal
* AI Provider
* Workspace

CLI

* Project Inspection
* Docker Generation
* Kubernetes
* CI/CD
* Documentation
* File Generation
* Repository Analysis
* Safety Rules

No engineering logic should be duplicated.

---

# 🔒 Safety Model

Every engineering request follows the same lifecycle.

```
User Request

↓

AI Analysis

↓

Plan Generation

↓

User Approval

↓

CLI Execution

↓

Terminal Streaming

↓

Workspace Update

↓

Session Saved
```

Nothing executes without approval.

---

# 💬 Engineering Timeline

Every engineering action becomes part of project history.

Example

```
09:10

Project Opened

↓

09:12

Repository Analysis

↓

09:14

Docker Generated

↓

09:18

Docker Build

↓

09:21

Kubernetes Generated

↓

09:28

Documentation Generated

↓

09:35

Completed
```

This makes every engineering session reproducible.

---

# ⚙ Technology Stack

Frontend

* HTML
* CSS
* JavaScript

Backend

* FastAPI
* WebSockets
* PTY

Core

* Sohail-Agent-CLI

AI

* Ollama
* Google Gemini API

Storage

* JSON
* Local Sessions
* Local Logs

Everything remains local.

---

# 🎨 Design Principles

* Local First
* Human Approval
* Transparent Execution
* Minimal Interface
* Keyboard Friendly
* Engineering Focused
* Fast
* Offline Friendly
* No Vendor Lock-in
* No Duplicate CLI Logic

---

# 🛣 Future Roadmap

## Phase 1

* Interactive Workspace
* AI Mentor
* Terminal Integration
* Ollama Integration
* Gemini API Integration
* Session Memory

## Phase 2

* 3D Knowledge Sphere
* Repository Graph
* Git Timeline
* Architecture Viewer
* Visual Logs

## Phase 3

* Voice Commands
* Multi-Agent Collaboration
* Plugin System
* Docker Visualizer
* Kubernetes Visualizer
* Terraform Graph
* Engineering Analytics

---

# ❤️ Long-Term Vision

Sohail Studio is not trying to replace the terminal.

It is not trying to replace IDEs.

It is not trying to replace AI assistants.

Instead, it connects all of them into a single engineering workspace where developers can think, plan, execute, and learn with complete transparency.

The goal is simple:

> **Open Sohail Studio. Open your project. Describe what you want. Review the plan. Approve the execution. Watch the engineering happen.**

Every command is visible.

Every action is explainable.

Every session becomes knowledge.

**Welcome to Sohail Studio — your local-first AI Engineering Workspace.**

