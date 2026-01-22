# Clean Code Rules for Python & PySpark

## 1. Unified Language & Naming
- All code must be written in English. German is only permitted for untranslatable technical domain terms.
- Use `snake_case` for all Python identifiers (variables, functions, methods, modules).
- Use descriptive, "speaking" names that convey intent.

## 2. Abstraction & Structure
- Maintain logic consistency: Use either Spark SQL or the PySpark API within a single module; do not mix both.
- Extract generic logic from domain-specific packages into utility or base modules.
- Avoid code duplication.
- File constraints:
  - Maximum 250 lines of code per file.
  - Maximum 7 files per package.

## 3. Quality & Type Safety
- Public functions MUST include Type Hints (Any does not count) and Docstrings.
- Error Handling: Avoid broad `except Exception:` blocks. Exception handling must be specific.
- Zero Tolerance: Resolve all IDE warnings and remove unused imports immediately.

## 4. Code Organization
- Imports: Must always be located at the top-level of the file.
- Function Length: Keep functions concise, ideally < 25 lines. Exception: Airflow DAG factories (`@dag`-decorated functions).
- Logging: Use the standard `logging` library. `print()` statements are prohibited.
- Comments: Avoid, but if necessary, explain the "Why," not the "What." No commented-out code blocks allowed.
- Keep code concise (e.g. fill lines if possible, no unnecessary parameter line breaks).
