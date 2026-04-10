@echo off
setlocal
conda activate research_tools
pytest tests -v
