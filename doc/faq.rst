Frequently Asked Questions
==========================

How do I get started with in Relate?
------------------------------------
At the start of a course, there are a few steps required to get going.
We assume that the Relate server is already installed and that you have
a user account there. Your account will need to have sufficient
privileges to create a course. (You can tell whether that's the case by
checking that there is a 'Set up new course' button at the bottom of the main
Relate page.)

Getting everything set up
^^^^^^^^^^^^^^^^^^^^^^^^^

-   Start by creating a Git repository on a hosting site (Github, Gitlab,
    Bitbucket, or similar) for your course.  Likely you will want this to be a
    private repository, to prevent students from seeing solutions to your
    assignments.

-   If you have a course repository from a prior semester, you can start by
    pushing its content to your new repository.

    If you're starting from scratch, you can use the
    `sample course <https://github.com/inducer/relate-sample>`__.
    You can either create your own and use it as a guide, or use
    it in its entirety and just make modifications.

-   Now you are ready to click that 'Set up new course' button.
    Fill out the form that pops up. For the 'Git source' field,
    use the SSH clone URL provided by your Git host. It shoud look
    like this::

        git@hostingsite.com:yourusername/yourreponame.git

    or like this::

        ssh://git@hostingsite.com/yourusername/yourreponame.git

-   To make sure Relate can access your course content, you will need
    an SSH keypair. Below the 'SSH private key', there is a link
    to a tool (built into Relate) to help you create one. Open that
    link in a new browser tab. Copy the 'private key' bit into the
    'SSH private key' box on the course creation form. Next, find
    the "Deployment key" section in the settings of your Git hosting
    site, and add the public key there. On Github, this is under
    "Setting/Deploy keys". On Gitlab, it is under "Settings/Repository/Deploy
    keys". For the title of the key, you may choose any description
    you like.

-   Fill out the rest of the form. You will want to pay special attention
    to whether you want your course listed on the main page, whether
    you would like it open for enrollment right away, who is allowed to enroll,
    and whether the site is restricted to staff. Nearly all of these settings can be
    changed later, under "Content/Edit Course", so if you make a mistake,
    it's note the end of the world. The only things that have to be correct
    at this point are the SSH settings, the the course identifier, course root,
    and the settings for 'course root' and 'course file' (but, in all
    likelihood, the defaults will be just fine).

    .. note::

        When choosing the 'course identifier', note that this will appear as
        part of the URL when students browse your course, so it is best to
        choose something that is easy to type and doesn't look out of place
        there, such as by preferring lower to upper case. It also has to be
        unique across the entire Relate site that you are using, so if the
        course you are teaching is expected to run multiple times, the
        identifier should likely include extra bits like the semester, and
        maybe even the name of the section.

        A common pattern is, e.g., ``cs450-f21`` for a course named `CS 450`
        running in the fall semester of 2021.

-   Once you hit 'Validate and create', Relate will try to download your
    course content via Git and check it for validity. This may take a second.
    Next, you should be greeted by your new course web page.

    If something went wrong, Relate will show an error message that
    explains what happened. If you can't figure out what it is trying to say,
    contact the site admin for your installation of Relate.

What to do next
^^^^^^^^^^^^^^^
At this point, you're off to the races! Here are some ideas for things you may
want to take care of next:

-   To update the course content, commit your changes, push them to your Git
    hosting site, select "Content / Retrieve/preview new course revisions" and
    click "Fetch and update" or "Fetch and preview".

-   You may also want to add your course staff so that they can help you
    get things set up. You can add them under "Grading / List of Participants",
    making sure to choose an appropriate role for them. Try to avoid giving
    one-off permissions. Instead, adjust the permissions of the role on
    the admin site.

-   If your course has controlled enrollment, you will likely want to
    recheck the enrollment settings under "Content/Edit course".

-   If you check "Enrollment approval required", you will receive an email
    (at the "Notify email" you provided) whenever a student tries to register.
    Approving these requests can be cumbersome. So you may want to create
    "enrollment preapprovals" for the students in your course, for example
    based on a class roster you have received. You can preapprove students
    either by institutional ID/student ID or by their email address.

-   Key dates in your course will be different every time your teach it, so Relate
    provides a notion of 'events' as symbolic names for specific points in time.
    (E.g. ``lecture 5``, ``quiz 3``, ``exam 2``). In addition to (optionally) being
    shown on the class calendar, you can refer to them from your course content,
    so that you don't have to manually change these dates every time you teach
    the course. If your  course content used events, you will likely have
    seen some warnings fly by about these being missing. (You can revisit those
    warnings by going to "Content / Retrieve/preview new course revisions" and
    clicking "Update" to rerun the validation.) Now might be a good time
    to add those events.

    Note that events may be numbered, as in the example above. If you need to create
    many events, note that there is a function "Content / Create recurring events"
    which lets you do so efficiently. If you have events that occur (e.g.) multiple
    times a week, create both series separately. At this point, however, the
    numbering will be off, with the second series numbered after the first.
    You can fix that by using the "Content / Renumber events" function, which
    adjusts the numbering so that it is in chronological order.

We hope you have a productive and fun course with Relate! If you have
ideas, comments, or suggestions, don't hesitate to `get in touch
<https://github.com/inducer/relate/issues/new>`__.

What does 'starting a session' mean?
------------------------------------

    Is there any way to allow students to click through a flow and just
    see the pages without starting a new session?

No, there isn't. Any and all visits to a page have to occur within a
session. But that is really just a technical requirement. What it means
for now is that at the beginning of it all, you have to click on a
button labeled start. (And, if that is an issue, that could be made to
go away quite easily.)

Overall, I would like you to get you away from thinking that starting a
session is this awful heavyweight thing that you can only afford to do a
few times before the system falls over. That's really not the
case. Session creation is quick and lightweight, and it just provides an
amount of context for a bunch of clicking around among a few pages.

What are 'flow sessions'?
-------------------------

    What are flow sessions representing to the
    student? What does starting a new session accomplish?

That said, yes, the technical requirement to have a session comes about
because there is a certain amount of state that (optionally) comes along
with a bunch of flow pages, such as (as you say) the shuffling of pages,
or the shuffling of options for multiple-choice questions, or
(hypothetically) any other type of thing that the page might decide to
do to adapt itself to a student. So, if what we're talking about is just
a bunch of static pages strung together, this whole notion of a session
is a bit artificial, and if it is an issue, we can work to sweep it
under the rug more thoroughly. On the other hand, as soon as we're
talking about assignments and quizzes and such, a session is a very
natural thing, as it serves as natural container for one round of
interacting with the pages in the flow (such as one attempt at a quiz).

   It seems like the student is abandoning
   all the previous interaction with the flow and starting over. Why
   would they want to do that?

Well, it is up to you when you write the flow rules whether you would
like the students to start a new session each time or whether you would
like to give them the option to return to a previous set of
interactions. This is covered under the "start" aspect of the flow
rules.

There are the following two options::

    -
        may_start_new_session: true
        may_list_existing_sessions: true

The first one indicates whether a student is allowed to start a new session,
and the second one indicates whether  a list of past sessions is shown
to resume or review.

Content Creation
================

What does the 'view' permission do?
------------------------------------

If you have it (the permission), you can see the pages in the flow. If
you don't have it, you can't.

Can flows be set up to branch somehow?
--------------------------------------

They are a purely linear affair for now, but at least technically it
wouldn't be hard to allow branching. Although I'm not sure I can imagine
what a sane authoring interface for that would look like.

Can participants do work in a flow that cannot be undone without starting a new session?
----------------------------------------------------------------------------------------

Yes. All work *can* be made undoable by adding the "change_answer"
permission, but by default, once an answer is "submitted", it cannot be
changed. (That is distinct from just "saving" an answer which makes the
system remember it but not consider it final.)

How do I have students realistically deal with data files in code questions?
----------------------------------------------------------------------------

Here's an example page to give you an idea::

    type: PythonCodeQuestion
    id: file_read_demo
    timeout: 3
    prompt: |

        # File Reading Demo

    data_files:
        - question-data/some.csv

    setup_code: |

        def open(filename, mode="r"):
            try:
                data = data_files["question-data/"+filename]
            except KeyError:
                raise IOError("file not found")

            # 'data' is a 'bytes' object at this point.

            from io import StringIO
            return StringIO(data.decode("utf-8"))

    names_for_user: [open]
    correct_code: |

        import csv
        with open("some.csv") as infile:
            reader = csv.reader(infile)
            for row in reader:
                print(row)

I wrote a Yes/No question, but RELATE shows "True/False" instead of "Yes/No"--why on earth would it do that?
------------------------------------------------------------------------------------------------------------

This is a bit of a misfeature in YAML (which relate uses), wich parses ``No`` as
a :class:`bool` instead of a literal string. Once that has happened, relate can't
recover the original string representation. To avoid that, just put quotes
around the ``"No"``.

Course Operations
=================

How do I launch an exam?
------------------------

An exam does not launch automatically when the header is changed. First, make
sure you have updated the course so the exam has the correct header in the public git revision.
Then, you must go to Grading -> Edit Exams, and activate the exam for the correct dates.
Most exam issues, like being unable to issue exam tickets, come from failing
to do one of the above two things.

How do I grant an extension for a particular student?
-----------------------------------------------------

Grant an exception (from say the gradebook or the grading menu) to the latest
session of the assignment you want to extend. Change the "Access Expires" to what you want it to be.
Make sure the correct access rules are checked. You will want it to generate a
grade (so check it), but make sure to set the credit percent to what you want
it to be.

Some events happen twice or three times in a week. How can I create create recurring events for that circumstance?
------------------------------------------------------------------------------------------------------------------

What I do in that case is create two recurring (weekly) event series (or three) and then renumber the result.

Sometimes we need to postpone or put in advance all the following events, which belong or not belong to the same kind of events, by a specific interval of time. How do I avoid editing events one by one?
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

"Delete one and renumber" might do the trick? That's what I do when, say, a class gets cancelled.


How do I manually upload a file for a student, after the deadline has passed?
-----------------------------------------------------------------------------

Typically, you can reopen the session with the appropriate access rules (from say, the gradebook),
impersonate the student, upload the file, and then submit the session to close it.
The previous steps may not work though if the flow rules are too restrictive.

How do I adjust a particular student's grade up?
------------------------------------------------

An easy way is to grant an exception for that student's quiz/homework/exam and
give them some number of bonus points. Note that this will also change the
number of points that the assignment is out of. To compensate, you must also change
the "maximum number of points" to the appropriate value. Remember to not grant
an access exception.
