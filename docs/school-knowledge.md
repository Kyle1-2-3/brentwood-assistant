# Public school knowledge

## Curated student clubs (2026/27)

`data/student_clubs.json` adds reviewed profiles for SAC, B-Well, BIPOC,
Women's Society, BEAT and OMNI, plus a directory for broad club questions.
It is loaded alongside the public website snapshot. Each club record retains
its own review date, academic year, source type and plain-text citations.
Named-club queries prioritize the current profile over older website mentions;
BWell/B-Well/B Well and Women's/Womens/Women Society spellings are normalized.
Club introductions include the purpose and regular meeting day, time and room,
even for a broad question such as "tell me abt sac". A recurring weekday in
the retrieved facts remains usable without a separate calendar `day_name` field.
Narrow questions still return only the requested detail.
All club overviews use the same three sections in order: **About** (brief
purpose), **People** (one bullet per confirmed role/contact), then
**Place & Time** (location followed by weekly day/time). Bare club names and
misspellings use the same layout; names, purpose and meeting details stay in
their own sections.

The November 2, 2026 review used school emails from September 2026 onward.
Joanna Fakulujo's October 5 reply directly explains BIPOC for the chatbot;
the other five profiles use school announcements. The project owner confirmed
on November 2 that all six clubs meet weekly and that the latest meeting notice
should supply the day, time and location. This overrides the October 18
Women's Society notice's older every-other-Monday wording.

Preserve the distinction between a meeting and a special event. SAC's October
27 cancellation applies only to that date. B-Well's latest available meeting
notice is September 11, at 6:30 PM in McNeill's (replacing the Killy); BEAT's
timed notice says 1:15 PM and later reminders say Tuesday lunch in C131.
OMNI's later 6:00 PM notices supersede the first meeting's 6:10 PM start.
Regular patterns do not by themselves verify a meeting on a particular date
or during a school break.

Future updates should prefer direct club explanations for descriptions and
the latest explicit notices for schedule changes, retaining dates and any
owner-confirmed corrections. Store concise club facts and source titles/dates,
not raw emails, recipients, personal email addresses, Gmail links/message IDs,
Classroom join codes, or form links. Source titles, dates and URLs stay internal:
student-facing chatbot answers contain no source citations, email titles,
attribution links or verification dates. The answer payload drops citation
metadata while retaining facts, academic years and uncertainty. Inbox access is only part of
manual maintenance, not application runtime. Restart workers after updates.

## Public website snapshot

The chatbot uses a versioned snapshot of official Brentwood public information in
`data/school_knowledge.json`. Each record has a topic, factual notes, an official
source URL, and the snapshot's verification date. `data/school_sources.json`
records coverage and exclusions. The snapshot contains no student accounts,
private calendar links, personal grades, or inferred student assignments.

Public facts such as the houseparent of Rogers, the contents of the Foote Centre,
library services, IT support, and course descriptions use `SCHOOL_INFO`. The
classifier translates the specific question into English search terms, including
the named person/place and context from follow-up questions. Local lexical search
selects a bounded set of relevant records; the answer must be supported by those
records without displaying sources. Missing information stays unknown.

`PERSONAL_SCHOOL` sends assigned teachers, advisors, classes, houses, roommates,
and student records to MySchool without retrieving public staff data or invoking
the answer model. Personal arts and sports retain their existing MySchool
redirect. Named-house public roles remain answerable. Public program descriptions
do not establish that a student is enrolled or that an activity is running today.

The website snapshot does not replace the live schedule, menu, sign-in, bedtime,
or manually maintained afternoon rules. The midnight calendar sync remains
separate. Website facts are **not automatically refreshed**: staff and facility
changes must be reviewed and committed before deployment.

User curation: omit generic Wi-Fi/network-login instructions and Wi-Fi amenity
details. Keep useful IT support and repair information. A specific staff-role
question should return that role and its source, without unrelated house facts.

## Updating the snapshot

1. Install `beautifulsoup4` in a maintenance environment (not required by the app).
2. Run `python scripts/collect_school_site.py --output /path/to/scratch`.
   This inventories every sitemap, reads the public information and course pages,
   and preserves extracted text/links for review. The historical blog, livestream,
   and taxonomy archives are inventoried separately, not treated as current policy.
3. Review the relevant source pages and update concise factual records. Preserve
   exact names, explicit date/year qualifications, provenance, and unique IDs.
   Do not infer personal assignments, requirements, hours, or staff responsibilities.
   Avoid copying marketing text or storing raw pages in this repository.
4. Update source coverage and the verification date. Check cross-page conflicts;
   prefer the dedicated department page over a broad overview and record decisions.
   Publicly linked external documents are pointers unless their contents are
   separately read and verified. Login-only content must not be marked as read.
5. Run `python -m pytest tests/ -q`, then check representative real questions,
   including a personal assignment, a public role, a facility, and a missing fact.
6. Commit and deploy. The application loads the snapshot once per worker, so a
   service restart is required to load a new version.

## Source conflict decisions for this snapshot

- **Allard house staff:** the September 2026 welcome page lists Kim Waugh as
  Houseparent and Sara Checkley as Assistant Houseparent; the general staff
  directory lists Adriane Rogers and Kim Waugh respectively. Related records
  include both sources and a conflict flag. Answers must disclose the mismatch
  and ask students to confirm with the school, rather than guess who is current.
- **Innovations location:** the dedicated Innovations page says the lower floor
  of the Centre for Innovation and Learning, around the corner from the Science
  Lab. The general student-services page still places IT in Crooks Hall. The
  dedicated page is used; the Crooks IT-location claim is excluded.
- Staff roles are public directory facts, not a student's teacher assignments.
  Source pages may list more than one person with a similar title; do not silently
  select a single person or invent an exclusive/current assignment.
- Opening-day house pages are used for house staff and partner-house facts only.
  Their dated orientation schedules are excluded from regular timetable answers.
