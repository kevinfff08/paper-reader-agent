@echo off
setlocal
conda activate research_tools
set PAPERREADER_TEST_MODE=1
pytest tests -v -p no:cacheprovider
