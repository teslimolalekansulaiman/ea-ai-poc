"""Cases: a sheet of items run through a use case, property by property.

  plan      what to look at for one property (its sources and queries), from its guidance
  gather    run that plan for one item and return labelled evidence
  solve     the model reads the evidence and answers; code verifies it and sets the status
  readiness the same plan + gather over sample items, without answering: is each property ready?
  engine    orders the properties, runs them concurrently, saves every cell, asks when it must
  store     the tables: cases, cells, events, questions
  summary   the result box, the row tags, the decisions and the suggested questions
"""
