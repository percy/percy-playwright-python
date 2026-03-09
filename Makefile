VENV=.venv/bin
REQUIREMENTS=$(wildcard requirements.txt development.txt)
MARKER=.initialized-with-makefile
VENVDEPS=$(REQUIREMENTS setup.py)

$(VENV):
	python3 -m venv .venv
	$(VENV)/python -m pip install --upgrade pip setuptools wheel
	yarn

$(VENV)/$(MARKER): $(VENVDEPS) | $(VENV)
	$(VENV)/pip install $(foreach path,$(REQUIREMENTS),-r $(path))
	$(VENV)/python -m playwright install
	touch $(VENV)/$(MARKER)

.PHONY: venv lint test test-coverage clean build release

venv: $(VENV)/$(MARKER)

lint: venv
	$(VENV)/pylint percy/* tests/*

test: venv
	npx percy exec --testing -- $(VENV)/python -m unittest tests.test_screenshot
	$(VENV)/python -m unittest tests.test_cache
	$(VENV)/python -m unittest tests.test_page_metadata
	$(VENV)/python -m unittest tests.test_init

test-coverage: venv
	$(VENV)/python -m coverage erase
	npx percy exec --testing -- $(VENV)/python -m coverage run --branch --parallel-mode -m unittest tests.test_screenshot
	$(VENV)/python -m coverage run --branch --parallel-mode -m unittest tests.test_cache
	$(VENV)/python -m coverage run --branch --parallel-mode -m unittest tests.test_page_metadata
	$(VENV)/python -m coverage run --branch --parallel-mode -m unittest tests.test_init
	$(VENV)/python -m coverage combine
	$(VENV)/python -m coverage report --fail-under=100
	$(VENV)/python -m coverage html
	$(VENV)/python -m coverage xml

clean:
	rm -rf $$(cat .gitignore)

build: venv
	$(VENV)/python setup.py sdist bdist_wheel

release: build
	$(VENV)/twine upload dist/* --username __token__ --password ${PYPI_TOKEN}
