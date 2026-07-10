You are moving toward the right architecture pattern: **a reusable Enterprise Document Intelligence Platform with pluggable business applications**.

The mistake many teams make is building:

```
Compliance App
    |
    ├── PDF parser
    ├── Vector search
    ├── AI prompts
    ├── Workflow tables

Supply Chain App
    |
    ├── PDF parser
    ├── Vector search
    ├── AI prompts
    ├── Workflow tables
```

This creates duplication and becomes impossible to maintain.

Instead, think like a platform team:

```
                    Enterprise Document Intelligence Platform

                              Shared Services

 ┌───────────────────────────────────────────────────────────────────┐
 │                                                                   │
 │ Document Ingestion Framework                                     │
 │ Document Processing Framework                                    │
 │ Entity Extraction Framework                                      │
 │ Metadata Framework                                               │
 │ Chunking + Embedding Framework                                   │
 │ Vector Search Framework                                          │
 │ Ontology Framework                                               │
 │ Agent Framework                                                  │
 │ Action / Workflow Framework                                      │
 │ Governance Framework                                             │
 │                                                                   │
 └───────────────────────────────────────────────────────────────────┘


                              Domain Modules

          ┌─────────────────┐       ┌────────────────────┐
          │ Supply Chain    │       │ Compliance Due      │
          │ Intelligence    │       │ Diligence           │
          └─────────────────┘       └────────────────────┘

          ┌─────────────────┐       ┌────────────────────┐
          │ Contract        │       │ Asset Intelligence  │
          │ Intelligence    │       │                    │
          └─────────────────┘       └────────────────────┘
```

The shared platform should be built once.

The domain modules should only contribute:

* schemas
* ontology
* extraction rules
* prompts
* agents
* business workflows

---

# Recommended Repository Structure

For Cursor/Claude Code, I would restructure the project into a modular monorepo.

```
doc-intelligence-platform/

│
├── platform/
│   ├── ingestion/
│   ├── document_processing/
│   ├── extraction/
│   ├── embeddings/
│   ├── vector_search/
│   ├── ontology/
│   ├── agents/
│   ├── workflows/
│   ├── governance/
│
│
├── domains/
│
│   ├── supply_chain/
│   │
│   │── schemas/
│   │── ontology/
│   │── prompts/
│   │── agents/
│   │── dashboards/
│   │── sample_data/
│
│
│   ├── compliance/
│       │
│       ├── schemas/
│       ├── ontology/
│       ├── prompts/
│       ├── agents/
│       ├── workflows/
│       ├── dashboards/
│       └── sample_data/
│
│
├── shared/
│   ├── configuration/
│   ├── utilities/
│   └── monitoring/
│
│
├── notebooks/
│
├── infrastructure/
│
└── README.md
```

---

# Component Breakdown and Claude Code Instructions

Below are the individual prompts I would give Claude Code.

---

# Component 1 — Core Document Intelligence Platform

## Purpose

Create the reusable foundation.

## Claude Code Instruction

```
You are building the shared foundation for an Enterprise Document Intelligence Platform.

Do not build any business-specific logic.

Create reusable components that support multiple domains.

The platform must support:

- Supply Chain
- Compliance
- Contract Intelligence
- Asset Intelligence

Build the following modules:

1. Document ingestion
2. Document storage
3. Metadata extraction
4. Document classification
5. Chunking
6. Embedding generation
7. Vector indexing
8. Retrieval services


Architecture requirements:

Bronze Layer:

Store raw documents exactly as received.

Create:

documents_raw

Fields:

document_id
source_system
file_name
file_type
created_timestamp
raw_location
domain
status


Silver Layer:

Create:

documents_processed

Fields:

document_id
document_type
entities_detected
classification
summary
extracted_text
confidence_score


Gold Layer:

Create:

document_knowledge_objects

Fields:

knowledge_object_id
entity_type
entity_id
document_id
relationship_type


Make every component domain agnostic.

No supply chain or compliance terminology should exist in this module.
```

---

# Component 2 — Enterprise Ontology Framework

## Purpose

Create reusable semantic modeling.

Claude Prompt:

```
Create an ontology framework that supports pluggable business domains.

The framework should define:

Core Enterprise Entities:

Organization
Person
Location
Document
Event
Asset
Risk
Requirement
Action


Create:

ontology/core/

and allow:

ontology/domains/


Example:

ontology/domains/compliance

ontology/domains/supply_chain


The framework must support:

- entities
- relationships
- attributes
- metadata
- lineage
- confidence scores


Create schemas that can represent:

Entity:
{
id,
type,
attributes,
source_documents,
confidence
}


Relationship:
{
source_entity,
relationship_type,
target_entity,
confidence
}


Do not create business-specific entities here.
```

---

# Component 3 — Action Management Framework

This should be shared.

This is the missing piece that makes Document Intelligence operational.

Claude Prompt:

```
Create an enterprise Action Management Framework.

The purpose is to convert document findings into tracked business actions.

Build:

actions

action_history

action_assignments

action_evidence

action_escalations


Support lifecycle:

Detected

Validated

Assigned

In Progress

Pending Review

Completed

Closed


Actions must support:

source_document

source_entity

priority

owner

due_date

status

evidence_required

escalation_rules


This framework must be reusable by:

Compliance violations

Supply chain disruptions

Contract obligations

Maintenance findings
```

---

# Component 4 — Compliance Due Diligence Module

This is the first domain implementation.

Claude Prompt:

```
Create a new domain module:

domains/compliance


This module represents AI-powered Store Development Compliance Due Diligence.

Do not modify platform components.


Build:


## Schema


Entities:


Project

FeasibilityRequest

Municipality

RegulatoryRequirement

License

Response

Action


Relationships:


Project LOCATED_IN Municipality

Municipality DEFINES Requirement

Request GENERATES Action

Response ANSWERS Request


## Documents


Generate synthetic examples:

- feasibility emails
- municipal requirements
- alcohol license documents
- zoning documents
- historical responses


## AI Capabilities


Create agents:


1. Intake Agent

Classify feasibility requests


2. Research Agent

Find municipality requirements


3. Historical Knowledge Agent

Find previous responses


4. Action Agent

Create and track tasks


## Questions


Support:


"What are the requirements for opening this store?"

"Have we answered this municipality before?"

"What changed since the last feasibility request?"

"What actions remain open?"
```

---

# Component 5 — Supply Chain Module

Existing demo becomes another plugin.

Claude Prompt:

```
Convert the existing Supply Chain Document Intelligence demo into a domain module.

Move all business-specific logic into:

domains/supply_chain


Create:

schemas

ontology

prompts

agents

sample_documents


Entities:

Supplier

Shipment

Product

Lot

Carrier

QualityIncident

TemperatureExcursion


Agents:


Supplier Risk Agent

Shipment Investigation Agent

Recall Agent


Do not duplicate:

document ingestion

vector search

action framework

ontology framework
```

---

# Component 6 — AI Agent Framework

Shared capability.

Claude Prompt:

```
Create an enterprise agent framework.

Agents must be configurable by domain.

Create:


agents/core

agents/domains


Each agent should have:

- system prompt
- tools
- knowledge sources
- ontology access
- action creation capability


Support:

Supervisor Agent

Specialized Agents


Example:


Compliance Supervisor

   |
   |
   ├── Municipality Agent
   ├── Historical Response Agent
   └── Action Agent


Supply Chain Supervisor

   |
   ├── Shipment Agent
   ├── Supplier Agent
   └── Recall Agent
```

---

# Component 7 — Databricks Implementation Layer

Claude Prompt:

```
Implement Databricks assets.

Create:

Unity Catalog structure:


catalog:

docintel


schemas:


platform

compliance

supply_chain


Create Delta tables:

platform.documents_raw

platform.documents_processed

platform.embeddings

platform.entities

platform.relationships

platform.actions


Create domain tables:

compliance.projects

compliance.requests

compliance.requirements


supply_chain.shipments

supply_chain.suppliers


Implement:

Lakeflow ingestion

Delta pipelines

Vector Search indexes

Mosaic AI Agent integration
```

---

# Component 8 — Demo Experience Layer

The demo needs a UI.

Claude Prompt:

```
Create a demonstration interface.

The UI should allow:

1. Upload documents

2. Ask questions

3. View extracted entities

4. View ontology relationships

5. View generated actions

6. View evidence


Create views:


Document Explorer

Ontology Explorer

AI Assistant

Action Tracker

Risk Dashboard


Support switching domains:

Supply Chain

Compliance

```

---

# How Your Existing Canvas Fits

Your existing:

```
docintel-architecture.canvas.tsx
```

should become the **platform architecture view**, not the application architecture.

It should show:

```
             Document Intelligence Platform

                    Shared Services

Bronze
 |
Silver
 |
Ontology
 |
Agents
 |
Actions


          Domain Applications

Compliance
Supply Chain
Contracts
Assets
```

Then create separate canvases:

```
compliance-architecture.canvas.tsx

supply-chain-architecture.canvas.tsx

action-management.canvas.tsx
```

---

# Recommended Build Order

Do not build all modules at once.

Build in this order:

## Phase 1

Foundation:

* Bronze/Silver/Gold
* Document ingestion
* Vector search
* Ontology framework

## Phase 2

Action Framework

This makes the demos operational.

## Phase 3

Compliance Due Diligence

Because it demonstrates:

* email intelligence
* document intelligence
* research agents
* workflow

## Phase 4

Supply Chain Plugin

Reuse everything.

---

The key architectural principle for Claude/Cursor is:

> **Build capabilities once in the platform layer. Build intelligence repeatedly in domain modules.**

That gives you a demo that looks like an enterprise Databricks implementation rather than two disconnected AI applications.

