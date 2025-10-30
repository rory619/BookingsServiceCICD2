APP = app.main:app
PID_FILE = .uvicorn.pid

.PHONY: install run test

install:
	 pip install -r requirements.txt

run:
	 python -m uvicorn $(APP) --host 0.0.0.0 --port 8000 --reload

test:
	 python -m pytest -q