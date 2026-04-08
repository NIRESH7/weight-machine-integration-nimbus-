#!/bin/bash

# Nimbus AWS Deployment Script (Ubuntu/Linux)

echo "--- Updating System ---"
sudo apt-get update -y

echo "--- Installing Python & Pip ---"
sudo apt-get install python3 python3-pip -y

echo "--- Installing Dependencies ---"
pip3 install -r requirements.txt

echo "--- Starting Nimbus Backend ---"
echo "Target: http://$(curl -s http://checkip.amazonaws.com):8000"
python3 nimbus_backend.py
