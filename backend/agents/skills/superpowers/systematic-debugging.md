# Systematic Debugging Skill

## Purpose
Debug errors methodically instead of randomly changing code.

## Process
1. **Reproduce**: Confirm the error is reproducible with a specific input
2. **Read the Error**: Parse the full stack trace:
   - What type of error? (TypeError, ValueError, RuntimeError, etc.)
   - Which line? Which file?
   - What was the call chain?
3. **Form Hypothesis**: Based on the error, form ONE specific hypothesis
   - "The variable X is None because Y was not initialized"
   - "The API returns a list but we're treating it as a dict"
4. **Test Hypothesis**: Add a single diagnostic (print, assert, or log)
5. **Fix or Iterate**: If hypothesis is correct, fix it. If not, form new hypothesis.

## Common Patterns
- **TypeError: NoneType**: Check if a function returns None on error path
- **KeyError**: Check if dict has the expected structure (API changed?)
- **ImportError**: Check if package is installed and path is correct
- **IndexError**: Check if list is empty before accessing elements
- **ConnectionError**: Check if service is running and accessible
- **JSONDecodeError**: Check if response is actually JSON (might be HTML error page)

## Anti-Patterns (AVOID)
- Changing multiple things at once
- Adding try/except to hide the error
- Rewriting the entire function
- Googling before reading the error message
- Assuming the error is in someone else's code

## Fix Verification
After fixing:
1. Run the original failing test/command
2. Run the full test suite
3. Manually verify the fix makes logical sense
