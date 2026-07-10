# Compliance Document Intelligence — Subject Area Specification

I think this is exactly the right direction. Rather than building **one large ontology**, build **multiple business subject areas** that share a common Document Intelligence framework. This is much closer to how large enterprises (including Databricks customers) organize their domains.

The architecture becomes:

```text
                 Enterprise Document Intelligence Platform
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     │                           │                           │
Supply Chain                Compliance                 Finance
Ontology                     Ontology                 Ontology
     │                           │                           │
     └───────────────────────────┼───────────────────────────┘
                     Shared Document Intelligence Layer
             Shared Lakehouse + Unity Catalog + Vector Search
```

This demonstrates that **Document Intelligence is reusable**, while each business domain has its own semantic model.

Below is a Cursor-oriented prompt that assumes the Supply Chain implementation already exists and instructs Cursor to create a **new Compliance subject area** without modifying the existing one.

---

# Cursor Project Prompt — Build a Compliance Document Intelligence Subject Area

## Project Context

The repository already contains an implementation of a **Supply Chain Document Intelligence** solution built on Databricks.

Do **not** modify, replace, or refactor the existing Supply Chain implementation.

Instead, create a **new business subject area** called **Compliance** that reuses the same overall architectural patterns while maintaining complete separation of concerns.

The Compliance subject area should have its own:

* ontology
* schema
* Delta tables
* sample documents
* document extraction pipeline
* AI agent
* dashboards
* semantic search indexes
* business questions

The goal is to demonstrate that Document Intelligence is a reusable enterprise capability that supports multiple domains through domain-specific semantic models.

---

# Architecture Principles

Reuse the existing enterprise architecture:

```text
Documents

↓

Lakeflow

↓

Bronze

↓

Document Intelligence

↓

Silver Entities

↓

Ontology Mapping

↓

Gold Semantic Objects

↓

Vector Search

↓

Mosaic AI Agent

↓

Business Questions
```

Only the business ontology changes.

---

# Subject Area

Create a new subject area named:

```text
Compliance
```

All assets should be namespaced accordingly.

Examples:

```
catalog.compliance

schema compliance

compliance_documents

compliance_entities

compliance_vector_index

compliance_agent

compliance_dashboard
```

Nothing should be mixed with Supply Chain assets.

---

# Business Objective

Build an AI-powered Compliance Knowledge System for a convenience retailer such as RaceTrac or QuikTrip.

The objective is to answer compliance questions from enterprise documents rather than transactional systems.

The system should understand:

* inspections
* permits
* licenses
* regulations
* violations
* corrective actions
* policies
* audit findings
* certifications

The emphasis is reasoning over documents, not simple retrieval.

---

# Compliance Domains

Model the following compliance domains independently but allow them to interrelate through shared entities such as Store, Employee, Vendor, Equipment, and Regulation.

## Environmental Compliance

Documents:

* UST inspections
* SPCC plans
* leak detection reports
* environmental audits
* EPA notices

Questions:

Which stores have unresolved environmental violations?

Which inspections generated corrective actions?

Which permits expire soon?

---

## Food Safety Compliance

Documents:

* health inspections
* sanitation audits
* HACCP reports
* temperature logs
* corrective action reports

Questions:

Which stores repeatedly fail food safety inspections?

Which refrigeration violations remain unresolved?

---

## OSHA / Safety

Documents:

* injury reports
* safety inspections
* PPE audits
* incident reports
* training certificates

Questions:

Which stores have overdue corrective actions?

Which employees require recertification?

---

## Fuel Operations

Documents:

* dispenser inspections
* tank inspections
* calibration reports
* fuel quality reports

Questions:

Which dispensers have overdue inspections?

Which tanks failed testing?

---

## Alcohol & Tobacco

Documents:

* licensing
* secret shopper reports
* compliance audits
* state inspections

Questions:

Which licenses expire soon?

Which stores repeatedly fail age-verification audits?

---

## Vendor Compliance

Documents:

* insurance certificates
* contracts
* supplier audits
* food safety certifications

Questions:

Which vendors have expired insurance?

Which suppliers lost certification?

---

# Document Corpus

Generate approximately 40–60 synthetic documents distributed across the compliance domains.

Suggested distribution:

* 10 inspection reports
* 5 audit reports
* 5 permits
* 5 licenses
* 5 corrective action plans
* 5 policy documents
* 5 email threads
* 5 training certificates
* 5 vendor certifications
* 5 incident reports

Each document should include realistic metadata such as:

* document_id
* document_type
* store_id
* region
* inspector
* issue_date
* expiration_date
* regulation_reference
* severity
* status

Use consistent naming conventions so entities can be resolved across documents.

---

# Compliance Ontology

Create a dedicated ontology.

## Entity Classes

Store

Inspection

Audit

Violation

Finding

CorrectiveAction

Permit

License

Policy

Regulation

Requirement

Inspector

Employee

Vendor

Equipment

Certification

Training

Incident

RiskAssessment

ComplianceProgram

Document

---

## Relationships

Store HAS Inspection

Inspection IDENTIFIED Finding

Finding RESULTED_IN Violation

Violation REQUIRES CorrectiveAction

CorrectiveAction ASSIGNED_TO Store

Store OPERATES Equipment

Equipment INSPECTED_DURING Inspection

Employee COMPLETED Training

Training SATISFIES Requirement

Vendor HOLDS Certification

Certification SUPPORTS ComplianceProgram

Permit AUTHORIZES Store

License ISSUED_TO Store

Policy IMPLEMENTS Regulation

Regulation DEFINES Requirement

Incident INVESTIGATED_BY Inspector

RiskAssessment EVALUATES Store

Document SUPPORTS Finding

---

# Delta Schema

Create separate Delta tables.

Bronze:

```
compliance_documents_raw
```

Silver:

```
inspection_entities

violation_entities

permit_entities

policy_entities

employee_training_entities

equipment_entities

vendor_entities

risk_entities
```

Gold:

```
compliance_store_profile

compliance_risk_scores

compliance_dashboard_metrics

compliance_graph_edges

compliance_graph_nodes
```

---

# Entity Resolution

Support canonical identities.

Example:

Store145

Location145

RaceTrac145

Station145

→

Store_145

Example:

EPA

Environmental Protection Agency

EPA Region IV

→

Regulation_Agency_EPA

Example:

UST

Underground Storage Tank

Fuel Tank Inspection

→

FuelTankInspection

---

# Document Intelligence

Every document should be parsed into structured business entities.

Extract:

organizations

people

equipment

dates

violations

regulations

permits

licenses

actions

deadlines

severity

locations

confidence scores

---

# Knowledge Graph

Construct graph nodes and relationships after extraction.

Example:

```
Store_145

HAS

Inspection_2025_032

Inspection

FOUND

Violation_44

Violation

REQUIRES

CorrectiveAction_19
```

---

# Vector Search

Create embeddings for every document chunk.

Metadata filters should include:

document_type

store

inspection_type

severity

status

regulation

expiration_date

region

Support hybrid retrieval using:

* semantic similarity
* metadata filtering
* ontology relationships

---

# AI Compliance Agent

Build an AI agent capable of answering questions using both semantic retrieval and ontology traversal.

The agent should explain its reasoning and reference the supporting documents and entities.

Example questions:

Which stores currently have unresolved EPA violations?

Which permits expire in the next 90 days?

Which stores have recurring violations for the same regulation?

Which corrective actions are overdue?

Which employees have expired certifications?

Which vendors have missing compliance documentation?

Which stores have the highest compliance risk score?

Which regulations are cited most frequently during inspections?

Show all documents supporting this compliance finding.

---

# Dashboards

Create AI/BI dashboards that summarize:

* Open vs. closed violations
* Violations by region
* Violations by regulation
* Corrective action aging
* Permit expiration timeline
* Certification status
* Inspection trends
* Store compliance scores
* Top recurring findings
* Vendor compliance status

---

# Success Criteria

The implementation is successful if:

1. The Compliance subject area is completely isolated from the Supply Chain subject area.
2. Both subject areas share the same architectural blueprint while maintaining independent ontologies and schemas.
3. Users can ask natural-language compliance questions and receive evidence-based answers synthesized across multiple documents.
4. Every answer is traceable to the underlying documents and ontology relationships.
5. The design is extensible so additional domains (Finance, HR, Asset Management, ESG, etc.) can be added using the same pattern without changing the shared Document Intelligence framework.

## Design Philosophy

Treat **Document Intelligence as the enterprise platform** and **business ontologies as plug-in subject areas**. The shared platform (Lakeflow, Delta Lake, Unity Catalog, AI Functions, Vector Search, and Foundation Model APIs) handles ingestion, governance, and retrieval, while each domain contributes its own schema, ontology, business rules, and AI use cases. This modular design demonstrates how a single Databricks-based foundation can support multiple business capabilities without coupling their semantic models, making it ideal for an enterprise-scale Document Intelligence platform.

Stop after generating the synthetic documents and loading them into the unity catalog volume. Test the execution of the remaining stages from the UI.
