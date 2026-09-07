# Ghost_Alert: Predictive IoT Hazard Detection system

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Current Solution Summary](#2-current-solution-summary)
3. [Our Solution: Ghost_Alert](#3-our-solution-ghost_alert)
4. [How It Works](#4-how-it-works)
5. [System Architecture Diagram](#5-system-architecture-diagram)
6. [Requirements](#6-requirements)
7. [Hardware Research](#7-hardware-research)
8. [Project Timeline](#8-project-timeline)
9. [Project Resources](#9-project-resources)

## 1. Project Overview
Ghost_Alert is an end-to-end IoT monitoring network designed for the predictive early warning of environmental hazards.

Traditional environmental monitoring relies on reactive sensors that only trigger after a disaster has occurred, or highly expensive industrial equipment that is difficult to scale. This project aims to bridge that gap by deploying a network of low-cost, active sensor nodes. By feeding high-frequency telemetry (soil saturation, micro-displacement, and motion events) into a time-series database, Ghost_Alert utilizes rolling rate-of-change analytics to predict catastrophic failures—such as landslides—before they happen, visualizing the threat on a real-time digital twin dashboard.

## 2. Current Solution Summary

| Solution | Sensor Intelligence | Data Architecture | Main Limitation |
| --- | --- | --- | --- |
| Basic IoT Thresholds | Reactive (Triggers when wet) | Relational SQL databases | Fails to predict velocity of change; high false-positive rate. |
| Industrial Geotech | Highly accurate, predictive | Proprietary, expensive software | Cost-prohibitive to deploy at scale across vast remote road networks. |
| **Ghost_Alert** | Predictive (Sensor Fusion) | Hybrid (PostgreSQL + InfluxDB) | Strikes a balance between low-cost edge hardware and advanced cloud analytics. |

## 3. Our Solution: Ghost_Alert

Ghost_Alert shifts the paradigm from *reactive alerting* to *predictive analytics*.

Instead of relying on a single static threshold, the system fuses data from multiple sensors (e.g., ADXL362 accelerometers and capacitive soil sensors) and evaluates them using a time-series database. By calculating the velocity of soil saturation over a sliding 15-minute window and cross-referencing it with gravitational micro-creep, the system can determine if a slope is actively failing. This data is ingested via a lightning-fast Python API and immediately projected onto a custom React-based administrative map for rapid response.

## 4. How It Works

The finalized Ghost_Alert architecture is divided into three functional layers, bridging autonomous edge hardware with a predictive cloud pipeline:

### 1. The Autonomous Edge Nodes (Hardware)

- **Power & Harvesting:** Nodes are completely grid-independent. They are powered by 3.7V 18650 Li-Ion cells, trickle-charged continuously by 5V mini solar panels via TP4056 protection modules.
- **Sensing & Processing:** An ultra-low-power microcontroller (Arduino Pro Mini 3.3V) manages the sensor payloads. It remains in deep sleep, waking only on interrupt (PIR motion) or scheduled intervals (landslide telemetry) to conserve power.
- **LPWAN Transmission:** Data is transmitted over long distances using SX1278 (433MHz) LoRa transceiver modules, bypassing the need for local Wi-Fi or cellular connections at the edge.

### 2. The Smart Gateway (Edge Processing)

- **LoRa Reception:** A locally deployed Raspberry Pi (Pi 3B+) acts as the central hub, equipped with a matching LoRa receiver to catch telemetry from all nodes within a multi-kilometer radius.
- **Forwarding:** The gateway formats the raw LoRa packets into structured JSON and pushes them over a secure internet connection to the cloud API.

### 3. Cloud Pipeline & The Digital Twin (Backend/Frontend)

- **Ingestion & Storage:** A FastAPI engine receives the payloads. Relational data (node lifecycles, active hazards) is stored in PostgreSQL, while high-frequency telemetry (voltage, moisture, tilt) streams into InfluxDB.
- **Predictive Logic:** Flux queries analyze historical data windows, applying rate-of-change mathematics to predict slope failures before they happen.
- **Visualization:** A React-based Leaflet web application serves as the command center, plotting live node health and highlighting active 50m hazard zones in real time.

## 5. System Architecture Diagram




## 6. Requirements

### Functional Requirements

- **FR1: Autonomous Power & Transmission:** The edge nodes shall utilize solar-harvesting and Li-Ion storage to maintain continuous operation, transmitting telemetry via LoRa LPWAN protocols.
- **FR2: Telemetry Ingestion:** The Raspberry Pi gateway shall bridge the LoRa network to the internet, pushing JSON telemetry to a RESTful FastAPI backend.
- **FR3: Time-Series Analysis:** The system shall utilize a time-series database to calculate the rate-of-change (RoC) of sensor data over a 15-minute window to predict hazard escalation.
- **FR4: Event Classification:** The backend shall classify events into discrete hazard categories (e.g., `wildlife_detected`, `landslide_imminent`) based on sensor fusion logic.
- **FR5: Interactive Visualization:** The frontend shall render a live web map plotting node locations, battery statuses, and highlighting active hazard zones.

### Non-Functional Requirements

- **NFR1: Power Efficiency:** The edge nodes shall achieve a sleep current low enough to sustain operation for at least 72 hours without direct sunlight.
- **NFR2: Transmission Range:** The LoRa communication layer shall reliably transmit data packets over a minimum distance of 1 kilometer in semi-obstructed outdoor environments.
- **NFR3: Ingestion Latency:** The FastAPI backend shall process incoming telemetry and update the database in under 200 milliseconds.

## 7. Hardware Research

The following components have been researched and selected based on local availability and optimal power-to-performance ratios for autonomous field deployment:

| Category | Component | Justification |
| --- | --- | --- |
| **Communication** | SX1278 (Ra-02) LoRa Module | Operates at 433MHz; inexpensive and readily available locally. Replaces the unviable backscatter approach. |
| **Edge Processing** | Arduino Pro Mini (3.3V / 8MHz) | Standard for micro-power nodes. Interfaces directly with 3.3V LoRa and sensors without logic shifters. |
| **Gateway** | Raspberry Pi (3B+) | Powerful enough to handle continuous LoRa reception and JSON forwarding to the cloud. |
| **Power Storage** | 18650 Li-Ion Cell (3.7V) | Ubiquitous and provides massive capacity for multi-day operation without sun. |
| **Energy Harvesting** | 5V Mini Solar Panel (~100mA+) | Locally available; sufficient to trickle-charge the 18650 cell. |
| **Charging Circuit** | TP4056 Module | Provides safe lithium battery charging and over-discharge protection. |
| **Sensors** | HC-SR501 PIR, ADXL362, Capacitive Soil V2 | 3.3V native components selected for minimal power draw and digital interrupt capabilities. |


## 8. Project Timeline

- **Week 1 (June 29 - July 5):** Project ideation, establishing the focus on environmental hazard detection and early warning systems.
- **Week 2 (July 6 - July 12):** Initial requirements definition and defining the scope of the hazards to monitor (wildlife and landslides).
- **Week 3 (July 13 - July 19):** System architecture evaluation. Identified limitations with the ambient RF backscatter concept for long-range outdoor deployment.
- **Week 4 (July 20 - July 26):** Hardware selection and initial BOM finalization. Began sourcing local components for bench testing.
- **Week 5 (July 27 - August 2):** Baseline sensor testing. Breadboard prototyping of the PIR and Capacitive sensors using C++ in the Arduino IDE to validate digital/analog readings.
- **Week 6 (August 3 - August 9):** Database engineering. Designed the relational schema in PostgreSQL (nodes, zones, hazards) and configured the InfluxDB buckets for time-series telemetry.
- **Week 7 (August 10 - August 16):** Backend pipeline development. Built the FastAPI server, establishing Pydantic models and RESTful `POST` endpoints for data ingestion.
- **Week 8 (August 17 - August 23):** Frontend core development. Scaffolded the React/Vite application and implemented the interactive Leaflet mapping engine.
- **Week 9 (August 24 - August 30):** Administrative UI development. Built the secure, state-driven Admin Hub for remote hardware provisioning and lifecycle management.
- **Week 10 (August 31 - September 6):** Predictive logic implementation. Integrated InfluxDB Flux queries into the Python backend to calculate soil saturation velocity and sustained micro-tilt.
- **Week 11 (September 7 - September 13) [CURRENT]:** End-to-end integration and final architecture pivot. Successfully tested the full software pipeline (predictive DB logic & map visualization) using active Wi-Fi benchtop nodes.
