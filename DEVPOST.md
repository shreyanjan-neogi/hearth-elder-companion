# Devpost submission text (copy and paste each section)

## Project name
Hearth

## Tagline
Voice check-ins for the people we look after.

## Track
Alexa+ (simulated Alexa+ experience, backed by a real self-hosted MCP server)

## Mini challenges
- **Open Source:** the repo is public under the MIT license. Read the mini-challenge rules on Devpost to confirm what
  extra fields it needs (contribution URL, GitHub username, short description) before ticking it.
- **AWS Builder:** do not tick this unless we add a documented AWS service. Hearth does not use one today.

## Was this project made before the hackathon?
No. Hearth was built entirely during the submission window.

## What it does
Hearth helps a family look after an older person who lives alone, without daily phone calls and without asking the
older person to learn anything new. They just talk to their voice assistant: "I took my morning pills", "I feel a bit
lonely", "I fell". Hearth records it, and a family member sees a short, honest summary on their phone: one headline,
anything that needs attention, today's medicines, mood, a week at a glance and any messages.

It is built around trust. It never gives medical advice and sends dose questions to a pharmacist or doctor. It says
"not confirmed" instead of "missed", because it only knows what it was told. It refuses to log a dose that is not due.
For falls, chest pain, trouble breathing, fainting or sudden confusion it alerts the caregiver at once and tells the
person to call local emergency services, because Hearth cannot.

## How we built it
- A **self-hosted MCP server** in Python (official MCP SDK) over **Streamable HTTP**, with 11 tools: daily check-in,
  medicines due today, what's next, log a dose, log mood, message or alert the caregiver, a caregiver summary, and
  setup tools. The negotiated protocol version is 2026-07-28, which is newer than the required 2025-11-25.
- A **simulated Alexa+ experience** as a web app: the person talks (browser speech recognition) or types, the
  assistant chooses tools and **calls the MCP server over real MCP**, and the reply is spoken back. A live panel shows
  each tool call so you can see the protocol at work.
- A **caregiver dashboard** that reads its data through the same MCP tools.
- SQLite storage, 30 automated tests (unit tests plus end-to-end tests that start the real server and talk to it
  over MCP), and one-click start scripts.

## Challenges we ran into
- Getting the safety behaviour right mattered more than any feature. Our own tests caught a gap: "I feel confused" was
  not triggering an alert, so we made confusion, fainting and disorientation always alert the caregiver.
- Telling a message to the caregiver ("let Priya know I took my pills") apart from actually taking pills.
- The newest MCP SDK renamed its main server class, so most online examples failed at first (see the friction log).

## Accomplishments we are proud of
- An end-to-end story that works: talk, tools, dashboard, alert.
- Safety rules that are enforced in code and covered by tests, not just written in a prompt.
- Anyone can run it with one double-click and no accounts.

## What we learned
MCP is a good fit for care tasks because the rules live in the tools. Whatever assistant sits in front, a dose that is
not due will not be logged and an emergency will always alert someone.

## What's next
- Test against a real Alexa+ device once available to us, and replace the pattern-based simulator with the assistant's
  own language understanding.
- Proper accounts and consent for the family, encrypted storage, and push notifications to the caregiver.
- Caregiver-set quiet hours and gentle follow-ups for unconfirmed doses.
- Support for more languages, starting with the ones our families speak at home.

## Built with
Python, MCP (Model Context Protocol, Streamable HTTP), Starlette, Uvicorn, SQLite, Web Speech API, HTML/CSS/JavaScript

## Repo
(paste your public GitHub URL here)

## Demo video
(paste your public YouTube or Vimeo URL here, under 3 minutes, in English)

---

## Product feedback (paste into the feedback box)

**MCP Python SDK (v2.3.0), `MCPServer`, `Client` and Streamable HTTP:** We used it to build the Hearth server and to
call it from our assistant simulator. Streamable HTTP worked the first time, passing the server object straight into
`Client` made tests fast, and `client.protocol_version` let us prove we meet the required spec version in a test.
What needed work: the rename from `FastMCP` to `MCPServer` broke every tutorial we tried first (the error message was
helpful, but a deprecation alias would be kinder), and tools that return a plain `dict` give no `structured_content`,
so we parsed JSON text instead. A short note in the docs would have saved time. We would build with it again.

**Alexa+:** We did not test against a real Alexa+ device or the Alexa+ Preview, so we have no direct feedback on
Alexa+ onboarding or tooling. Our simulated experience stands in for the assistant.

**AWS services:** none used.

(Details of what we hit, with severity and workarounds, are in `FRICTION_LOG.md` in the repo.)
