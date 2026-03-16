# Brainstorming Skill

## Purpose
Generate comprehensive specifications from vague requirements through structured brainstorming.

## Process
1. **Understand the Request**: Parse the user's goal and identify key components
2. **Ask Clarifying Questions** (internally): What are the inputs? Outputs? Edge cases? Performance requirements?
3. **Generate Multiple Approaches**: Come up with at least 3 different implementation strategies
4. **Evaluate Trade-offs**: Compare approaches on: complexity, performance, maintainability, correctness
5. **Select Best Approach**: Choose the approach that best balances trade-offs
6. **Write Specification**: Document the chosen approach with:
   - Clear requirements
   - Input/output formats
   - Error handling strategy
   - Performance considerations
   - Test scenarios

## Output Format
```
## Specification: [Task Name]

### Requirements
- [Requirement 1]
- [Requirement 2]

### Approach
[Selected approach with justification]

### Data Flow
[Input] -> [Processing] -> [Output]

### Edge Cases
- [Edge case 1]: [Handling]
- [Edge case 2]: [Handling]

### Test Scenarios
1. [Happy path test]
2. [Edge case test]
3. [Error handling test]
```

## When to Use
- Complex features (>100 estimated lines)
- Architecture decisions
- Multi-component systems
- Unclear or vague requirements
