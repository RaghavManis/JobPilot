# Project Descriptions — Manish Yadav

## Project 1: JobPilot — AI Universal Job Application Agent

### Overview
JobPilot is an AI-assisted browser automation project designed to handle job applications across different recruitment websites. It aims to identify form fields, use verified candidate profile information to generate answers, and navigate multi-step application workflows with human oversight.

### Key Technical Features
- **Browser Automation:** Uses Playwright to inspect web pages, identify interactive form fields, and automate form interactions.
- **AI-Powered Form Filling:** Uses LLMs to interpret application questions and map them to relevant information from the candidate profile and resume.
- **Knowledge Retrieval:** Designed to incorporate retrieval-based access to verified candidate information, reducing unsupported or fabricated answers.
- **Multi-Page Workflows:** Designed to handle Next, Continue, and Save & Continue actions across application pages.
- **Human-in-the-Loop:** Intended to pause for manual intervention when login, CAPTCHA, ambiguous questions, or final submission requires user involvement.
- **Technology Stack:** Python, FastAPI, Playwright, LLM APIs, LangChain, LangGraph, and retrieval-based knowledge systems.

**Current status:** Under development. The initial backend architecture and foundational API routes have been implemented. Features described as intended capabilities should not be represented as fully implemented until verified.

## Project 2: Cricket Tournament Management System

### Overview
A web application for managing cricket tournaments, matches, and live scoring, with a backend API and interactive frontend.

### Key Technical Features
- Developed backend services using Java, Spring Boot, Spring Security, Hibernate/JPA, and MySQL.
- Implemented authentication and authorization using JWT.
- Integrated WebSockets for live score updates.
- Built the frontend using React, TypeScript, and Vite.
- Optimized database access by addressing N+1 query issues and applying caching, reducing database API consumption by approximately 90%.
- Implemented cricket scoring rules, including no-ball handling and strike rotation after run-outs.

**Live Demo:** https://splcricket.live/dashboard

## Project 3: Uber-Style Microservices Backend

### Overview
A backend application inspired by ride-hailing platforms, designed around independently organized services and API-based communication.

### Key Technical Features
- Built multiple Spring Boot microservices, including an authentication service.
- Implemented JWT-based authentication and role-based access control using Spring Security.
- Used MySQL for persistent storage and Flyway for database migrations.
- Integrated Kafka for event-driven communication.
- Used Redis caching to improve response times.
- Worked with service discovery using Eureka and real-time communication using WebSockets and STOMP.

**Repository:** https://github.com/RaghavManis/UberProject-AuthService

## Project 4: Enterprise AI Assistant — RAG & Multi-Agent System

### Overview
An AI assistant project focused on retrieving relevant information from documents and coordinating LLM-powered tasks through structured workflows.

### Key Technical Features
- **Retrieval-Augmented Generation (RAG):** Uses document retrieval concepts to ground responses in relevant source material.
- **Embeddings and Vector Search:** Uses embeddings and FAISS concepts to retrieve semantically relevant information.
- **Agent Orchestration:** Explores LangChain and LangGraph for workflow routing, tool calling, and state management.
- **Context Management:** Incorporates concepts such as memory and human-in-the-loop review.
- **Backend Integration:** Uses Python and FastAPI for application interfaces, with Docker for containerization.

**Technology Stack:** Python, LangChain, LangGraph, LLM APIs, FAISS, FastAPI, and Docker.

## Instructions for Answering Project-Related Questions

- Use only the technologies, responsibilities, and outcomes documented for each project.
- Distinguish implemented features from planned features, especially in JobPilot and the Enterprise AI Assistant.
- Do not invent performance metrics, user counts, deployment scale, or business impact.
- For questions about challenges, architecture, design decisions, or lessons learned, generate an explanation grounded in the project's actual implementation.
- If asked about a feature that has not been verified as implemented, clearly describe it as planned, under development, or a concept explored.
