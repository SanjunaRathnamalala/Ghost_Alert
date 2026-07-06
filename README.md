# Ghost_Alert: IoT Hazard Detection system with zero-powered sensor nodes

## 📌 Project Overview
Ghost_Alert is an ultra-low-power, ambient RF backscatter system designed for early hazard detection. 

Traditional IoT remote sensor networks require batteries, which are expensive to maintain and environmentally toxic to replace at scale. This project aims to build a network of "zero-power" sensor nodes that harvest their operating energy entirely from surrounding ambient radio waves (such as 4G LTE or Wi-Fi). These nodes monitor for real-world environmental hazards like, wildlife road crossings, track intrusions or landslides, and transmit alerts back to a central gateway without ever needing a battery or mains power.

## 🚀 How It Works

The system architecture is divided into two main components:

### 1. The Passive Sensor Nodes (The "Ghosts")
* **Energy Harvesting:** The nodes capture ambient RF energy from the environment using an antenna and a highly efficient rectifier circuit, storing it in a supercapacitor.
* **Sensing:** Once enough energy is harvested, an ultra-low-power microcontroller wakes up to take a reading from a connected sensor (e.g., PIR motion, soil moisture).
* **Backscatter Modulation:** Instead of generating their own radio waves to transmit the data (which consumes too much power), the nodes use an RF switch to alter their antenna's impedance. This acts as an "RF mirror," embedding the sensor data into the reflected ambient radio waves.

### 2. The Smart Gateway
* **Signal Decoding:** A powered roadside gateway receives the backscattered signals. It uses interference cancellation to filter out the loud ambient waves and isolate the faint, reflected sensor data.
* **Alert Broadcasting:** Once the hazard data is processed, the gateway rebroadcasts a formatted, high-power warning to approaching vehicles (via V2X communication) or uploads the alert to a cloud-based mapping platform.

## 🛠️ Current Status
* **Phase:** Initial Repository Setup & Conceptual Architecture.
* **Next Steps:** * Prototype the RF energy harvesting circuit.
  * Test ultra-low-power MCU sleep/wake cycles.
  * Develop the backscatter modulation logic.