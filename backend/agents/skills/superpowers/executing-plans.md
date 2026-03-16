# Executing Plans Skill

## Purpose
Break down a specification into an ordered, executable plan with clear milestones.

## Process
1. **Parse Specification**: Extract requirements, constraints, and test scenarios
2. **Identify Components**: List all files, functions, classes, and modules needed
3. **Determine Dependencies**: Map which components depend on others
4. **Order by Dependency**: Create bottom-up execution order (dependencies first)
5. **Define Milestones**: Group steps into testable milestones
6. **Estimate Complexity**: Rate each step (simple/medium/complex)

## Output Format
```
## Execution Plan: [Task Name]

### Milestone 1: [Foundation]
- [ ] Step 1.1: [Description] (simple)
- [ ] Step 1.2: [Description] (medium)
  Checkpoint: [How to verify milestone 1 is complete]

### Milestone 2: [Core Logic]
- [ ] Step 2.1: [Description] (complex)
- [ ] Step 2.2: [Description] (simple)
  Checkpoint: [How to verify milestone 2 is complete]

### Milestone 3: [Integration & Testing]
- [ ] Step 3.1: [Description] (medium)
  Checkpoint: [Final verification]
```

## Rules
- Each step should be independently verifiable
- No step should take more than 50 lines of code
- Include "undo" strategy for each step in case it fails
- Checkpoints must be concrete (run a test, check output, verify file exists)
