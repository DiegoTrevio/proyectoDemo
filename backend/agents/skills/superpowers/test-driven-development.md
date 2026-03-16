# Test-Driven Development Skill

## Purpose
Write tests BEFORE implementation to ensure correctness from the start.

## Process (Red/Green/Refactor)
1. **RED: Write a failing test**
   - Write the simplest test that captures one requirement
   - Run the test — confirm it FAILS (this validates the test itself)

2. **GREEN: Write minimal code to pass**
   - Write the absolute minimum code to make the test pass
   - No extra features, no optimization, no cleanup
   - Run the test — confirm it PASSES

3. **REFACTOR: Clean up**
   - Now that tests pass, improve the code
   - Remove duplication, improve naming, optimize
   - Run tests again — confirm they still PASS

4. **Repeat**: Go back to RED for the next requirement

## Test Writing Guidelines
- Test names should describe the behavior: `test_returns_empty_list_when_no_results`
- One assertion per test (prefer focused tests)
- Test edge cases: empty input, None, maximum values, special characters
- Test error cases: invalid input should raise appropriate exceptions
- Use fixtures for common setup
- Mock external dependencies (APIs, databases, file system)

## Test Structure
```python
def test_[behavior_being_tested]():
    # Arrange: Set up test data
    input_data = ...

    # Act: Call the function
    result = function_under_test(input_data)

    # Assert: Verify the result
    assert result == expected
```

## When to Skip TDD
- Simple scripts (<20 lines)
- One-off data transformations
- Exploratory/prototyping code
