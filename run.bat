@echo off
title PyStreamFlow
cd /d "%~dp0"
call venv\Scripts\activate
python -m streamlit run pystreamflow.py
