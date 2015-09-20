Frequently Asked Questions
==========================

What does the 'view' permission do?
------------------------------------

If you have it (the permission), you can see the pages in the flow. If
you don't have it, you can't.

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
