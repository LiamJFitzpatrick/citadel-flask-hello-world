# Agent Guidelines for citadel-flask-hello-world

## 1. Build, Lint, and Test Commands

### Building the Application
- Docker build: `docker build -t citadel-flask-hello-world .`
- Running the container: `docker run -p 5000:5000 citadel-flask-hello-world`
- To rebuild without cache: `docker build --no-cache -t citadel-flask-hello-world .`
- To run in detached mode: `docker run -d -p 5000:5000 citadel-flask-hello-world`
- To stop a running container: `docker stop <container_id>` (find container_id with `docker ps`)

### Linting
- Since there is no linting configuration, we recommend using:
  - Flake8: `flake8 hello-world/`
  - Pylint: `pylint hello-world/`
  - To install linting tools: `pip install flake8 pylint`
- Example Flake8 configuration (if added in `.flake8`):
  ```
  [flake8]
  max-line-length = 88
  extend-ignore = E203, W503
  ```
- Example Pylint configuration (if added in `.pylintrc`):
  ```
  [MASTER]
  init-hook='import sys; sys.path.append(".")'
  ```
- To run both linters via a Makefile (if created):
  ```
  lint:
  	flake8 hello-world/
  	pylint hello-world/
  ```

### Testing
- Currently, there are no tests in the project.
- If tests are added, they can be run with pytest:
  - Install pytest: `pip install pytest`
  - Run all tests: `pytest`
  - Run a single test file: `pytest tests/test_specific.py`
  - Run a single test function: `pytest tests/test_specific.py::test_function_name`
  - Run tests with coverage: `pytest --cov=hello-world tests/`
  - To run tests in verbose mode: `pytest -v`
- Example test file structure for Flask (if tests are added):
  ```python
  # tests/test_app.py
  import pytest
  from hello-world.app import app

  @pytest.fixture
  def client():
      app.config['TESTING'] = True
      with app.test_client() as client:
          yield client

  def test_hello_world(client):
      response = client.get('/')
      assert response.status_code == 200
      assert b'<p>Hello, World!</p>' in response.data
  ```
- If using the Flask test client, remember to set `app.config['TESTING'] = True`.

## 2. Code Style Guidelines

### Imports
- Standard library imports first (e.g., `import os`, `import sys`).
- Third-party imports second (e.g., `from flask import Flask`, `import numpy as np`).
- Local application/library imports last (e.g., `from .utils import helper_function`).
- Each group should be separated by a blank line.
- Use absolute imports for local modules when possible (e.g., `from hello-world.utils import helper_function`).
- Avoid relative imports in packages unless necessary.
- Import specific classes/functions when possible (e.g., `from os import path` instead of `import os` if only using `path`).

### Formatting
- Follow PEP 8 for Python code.
- Line length: 79 characters (or 88 if using Black, but not currently configured).
- Indentation: 4 spaces per level (no tabs).
- Use double quotes for strings unless the string contains a double quote, then use single quotes.
- No trailing whitespace.
- Maximum two blank lines between function/class definitions, one blank line between methods.
- Use spaces around operators and after commas, but not inside parentheses.
- Example of proper formatting:
  ```python
  def example_function(arg1, arg2):
      """Example function with proper formatting."""
      if arg1 > arg2:
          return arg1 - arg2
      return arg1 + arg2
  ```

### Types
- Although this is a small Flask app, if type hints are added, use Python 3.6+ syntax (e.g., `def func(arg: str) -> int:`).
- For Flask route functions, return types are typically `str` or `Response`.
- Use `typing` module for complex types (e.g., `List[str]`, `Dict[str, int]`).
- For variables that can be multiple types, use `Union` (e.g., `Union[str, int]`).
- For optional values, use `Optional` (e.g., `Optional[str]` is equivalent to `Union[str, None]`).
- Example with type hints:
  ```python
  from typing import List, Optional, Union

  def process_items(items: List[str], limit: Optional[int] = None) -> Union[str, List[str]]:
      if limit:
          return items[:limit]
      return items
  ```

### Naming Conventions
- Modules and packages: lowercase_with_underscores (e.g., `hello_world`, `utils`).
- Classes: CapWords (PascalCase) (e.g., `HelloWorld`, `DataProcessor`).
- Functions and methods: lowercase_with_underscores (e.g., `hello_world`, `process_data`).
- Constants: UPPERCASE_WITH_UNDERSCORES (e.g., `MAX_CONNECTIONS`, `DEFAULT_TIMEOUT`).
- Instance attributes and variables: lowercase_with_underscores (e.g., `user_name`, `total_count`).
- Private attributes/methods: single leading underscore (e.g., `_private_var`, `_internal_method`).
- Special methods (dunder): double leading and trailing underscores (e.g., `__init__`, `__str__`).

### Error Handling
- Use try-except blocks to catch specific exceptions.
- Avoid bare except clauses; always specify the exception type.
- Log errors appropriately (if logging is set up) using the `logging` module.
- In Flask, use error handlers for HTTP exceptions (e.g., `@app.errorhandler(404)`).
- Example of proper error handling:
  ```python
  import logging
  from flask import jsonify

  logger = logging.getLogger(__name__)

  @app.route('/user/<int:user_id>')
  def get_user(user_id):
      try:
          user = User.query.get(user_id)
          if not user:
              raise ValueError(f"User {user_id} not found")
          return jsonify(user.to_dict())
      except ValueError as e:
          logger.warning(f"User lookup failed: {e}")
          return jsonify({"error": str(e)}), 404
      except Exception as e:
          logger.error(f"Unexpected error in get_user: {e}")
          return jsonify({"error": "Internal server error"}), 500
  ```
- For Flask, consider using `@app.errorhandler` for common HTTP errors:
  ```python
  @app.errorhandler(404)
  def not_found(error):
      return jsonify({"error": "Resource not found"}), 404

  @app.errorhandler(500)
  def internal_error(error):
      return jsonify({"error": "Internal server error"}), 500
  ```

### Flask-Specific Guidelines
- Keep route functions lean; move business logic to separate functions or modules.
- Use templates for HTML (located in the `templates` directory) and keep logic out of templates.
- Do not perform heavy computations in route functions; consider background tasks (e.g., Celery) for long-running jobs.
- Use Flask's configuration object for environment-specific settings (e.g., `app.config.from_envvar('APP_SETTINGS')`).
- Secure your application by using Flask-WTF for forms, Flask-Login for authentication, etc., as needed.
- Use blueprints to organize large applications (e.g., `from flask import Blueprint`).
- Example of a blueprint:
  ```python
  from flask import Blueprint

  bp = Blueprint('api', __name__, url_prefix='/api')

  @bp.route('/hello')
  def hello():
      return {"message": "Hello, World!"}
  ```
- Register blueprints in the main app:
  ```python
  from hello-world.api import bp as api_bp
  app.register_blueprint(api_bp)
  ```

## 3. Additional Notes

- The project uses Gunicorn as the WSGI server (as seen in the Dockerfile).
- The application is structured with a single `app.py` file; as the project grows, consider using the application factory pattern and blueprints.
- The Dockerfile uses a multi-stage build? Currently, it's a single stage. Consider using multi-stage builds for smaller images.
- The virtual environment is located at `.venv` and is ignored by Git.
- Environment variables should be stored in a `.env` file (ignored by Git) and loaded using python-dotenv if needed.
- For development, consider using Flask's built-in server with `flask run` or `python -m flask run`.
- To set Flask environment variables: `export FLASK_APP=hello-world/app.py` and `export FLASK_ENV=development`.

## 4. Copilot Instructions

We checked for existing Copilot instructions in `.github/copilot-instructions.md` but none were found.
We also checked for Cursor rules in `.cursor/rules/` and `.cursorrules` but none were found.
