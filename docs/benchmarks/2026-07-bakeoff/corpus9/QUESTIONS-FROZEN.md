# Corpus-9 frozen question keys — authored from each video's captions (source of truth)
# BEFORE any arm ran. Hash committed = preregistration. 2 questions per substantive
# video (1 dependency family each); music videos are unscored caption-robustness canaries.
# Arms compared: original (bradautomates/claude-video @83da59f) vs ours (v1.2.2) balanced
# + ours evidence (engages only on videos >9min). Grading 0/1/2 vs KEY, blind.

## V1 iG9CE55wbtY — Ken Robinson "Do schools kill creativity?" (TED, 20min) [talk]
Q1 (targeted): What is Robinson's central thesis about schools and creativity?
KEY: Schools/education systems kill (educate people out of) creativity; creativity should be treated as equal in status to literacy.
Q2 (summary): Tell the Gillian Lynne story and its point.
KEY: A girl thought to have a learning disorder was actually a dancer; a specialist saw she needed to move, sent her to dance school; she became a famous choreographer (Cats, Phantom). Point: someone else might have medicated her. Different kinds of intelligence/talent.

## V2 ZDa-Z5JzLYM — Corey Schafer "Python OOP 1: Classes and Instances" (15min) [screencast]
Q1 (targeted): What is the difference between a class and an instance?
KEY: A class is a blueprint/template; an instance is a specific object created from that class (each employee is an instance of the Employee class).
Q2 (numeric/mechanical): What does the __init__ method's first parameter (self) do, and how are methods called?
KEY: self is the instance, passed automatically; __init__ initializes instance attributes; methods can be called on an instance or via the ClassName passing the instance explicitly.

## V3 zjkBMFhNj_g — Karpathy "Intro to Large Language Models" (60min) [talk]
Q1 (targeted): In Karpathy's framing, what "is" a large language model, concretely?
KEY: Two files — a parameters file (the weights, e.g. ~140GB for Llama-2-70B) plus a small run/code file. The magic is in the parameters.
Q2 (summary): How is the model trained, and what is a "universal transferable suffix"?
KEY: Training compresses a large chunk of the internet using a GPU cluster (expensive, days). A universal transferable suffix is a jailbreak — an appended string that breaks the model's safety alignment.

## V4 QacqRZ0vsD4 — "top GitHub repos of the week" (43min) [talk, cached]
Q1 (targeted): Which repo lets Claude watch video, and its stats?
KEY: bradautomates/claude-video; ~6.6k stars, Python, the #10 pick.
Q2 (numeric): How many repos does the episode cover and what's the format?
KEY: The top ~13 trending GitHub repos of the week, reacted to by Andrew and Adam over screen-share.

## V5 ZW6d_2rwcdk — "Master 95% of Claude Code in 22 Minutes" (22min) [screencast, cached]
Q1 (targeted): What is the video teaching and for whom?
KEY: How to build real working apps with Claude Code (in the Claude Desktop app), for beginners, without touching a terminal.

## V6 rBpaUICxEhk — Alan Watts "Life is NOT a Journey" (4min) [short]
Q1 (targeted): What is Watts's central analogy for life?
KEY: Life is best understood by analogy with music/dancing — the point is the playing/dancing itself, not arriving at a destination/end; we mistakenly treat life as a journey to a goal.

## V7 zQnBQ4tB3ZA — "TypeScript in 100 Seconds" (2.4min) [short, cached]
Q1 (targeted): What is TypeScript and what does it add to JavaScript?
KEY: A superset of JavaScript that adds static types; compiles/transpiles to plain JS; catches type errors at compile time.

## CANARIES (unscored — caption robustness only)
## C1 9bZkp7q19f0 — Gangnam Style (Korean music, auto-translated caps): does the tool run without crashing?
## C2 dQw4w9WgXcQ — Rick Astley (music): does the tool run without crashing?
