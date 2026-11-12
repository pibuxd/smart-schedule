"""Pure-Python scheduling engine (problem model, validator, scoring, solver).

Must not import Django: the Django layer builds a `Problem` and passes it in.
`problem` describes the task, `validator` checks a schedule against it, `scoring` turns the check into the
three numbers the manager sees. The solver arrives in stage 5.
"""
