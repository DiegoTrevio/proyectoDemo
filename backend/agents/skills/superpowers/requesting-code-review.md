# Requesting Code Review Skill

## Purpose
Self-review generated code for quality, security, and correctness before delivering.

## Review Checklist

### 1. Correctness
- [ ] Does the code actually solve the stated problem?
- [ ] Are all edge cases handled?
- [ ] Do the tests pass?
- [ ] Are error paths handled (not just happy path)?

### 2. Security
- [ ] No hardcoded secrets or credentials
- [ ] Input validation on all external data
- [ ] No SQL injection, XSS, or command injection vectors
- [ ] Proper authentication/authorization checks
- [ ] No unsafe deserialization

### 3. Performance
- [ ] No O(n^2) or worse algorithms where O(n) is possible
- [ ] No unnecessary network calls or database queries
- [ ] Large data sets use streaming/pagination
- [ ] No memory leaks (unclosed connections, growing lists)

### 4. Readability
- [ ] Clear variable and function names
- [ ] Functions do one thing (single responsibility)
- [ ] No deeply nested conditionals (max 3 levels)
- [ ] Comments explain "why", not "what"

### 5. Robustness
- [ ] Graceful degradation on external service failure
- [ ] Timeouts on all network calls
- [ ] Proper logging (not print statements)
- [ ] Configuration via environment variables, not hardcoded

## Review Output
```
## Code Review Summary

### Score: [1-10]

### Issues Found
- [CRITICAL] [Description] at line [N]
- [WARNING] [Description] at line [N]
- [SUGGESTION] [Description]

### Approved: [YES/NO]
[If NO, list required changes before approval]
```
