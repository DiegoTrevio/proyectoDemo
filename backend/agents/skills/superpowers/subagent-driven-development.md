# Subagent-Driven Development Skill

## Purpose
Break complex tasks into parallel subtasks that can be handled by specialized agents.

## Process
1. **Decompose**: Split the main task into independent subtasks
2. **Assign**: Map each subtask to the best specialist:
   - Researcher: gather information, find APIs, read docs
   - Coder: write implementation code
   - Validator: write tests, review code
   - Document Writer: create docs, READMEs
3. **Parallelize**: Identify which subtasks can run simultaneously
4. **Coordinate**: Define interfaces between subtask outputs
5. **Integrate**: Combine all subtask results into final output

## When to Use
- Task has >3 independent components
- Different expertise needed (research + code + docs)
- Time-sensitive tasks that benefit from parallelism
- Large codebase changes spanning multiple files

## Coordination Pattern
```
Main Task
├── [Parallel] Research subtask → findings
├── [Parallel] Scaffold subtask → project structure
│
├── [Sequential] Implementation subtask (uses findings + scaffold)
│
├── [Parallel] Test subtask → test results
├── [Parallel] Doc subtask → documentation
│
└── [Final] Integration subtask → verified output
```

## Rules
- Each subtask must have clear input/output contract
- Subtasks should not have circular dependencies
- Always include a validation subtask at the end
- If a subtask fails, don't retry more than once — adapt the plan
