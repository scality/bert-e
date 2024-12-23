__Bert-E__'s user documentation
===============================

Who is this guy called __Bert-E__ that just greeted me?
-------------------------------------------------------
__*Bert-E* is the robot that merges new code in the different development
branches of the repository.__

The development branches of the repository (_in GIT: branches named
development/\..._) is where the new code lands after a series of tests and
validations. There are strong requirements on the code that is on these
branches. The most important requirements being:

  * the code has been validated,
  * and the code that is included in one development branch must also be on all
    subsequent branches.

Therefore, only one person can write on these branches, and this person is a
robot: __Bert-E__!

__Bert-E__ interacts with the pull requests that are created in Bitbucket. His
never-ending task is to merge the changesets they contain on the development
branches. Before he does so, he checks a number of vital points, and will give
helpful hints to developers, to help them achieve the merge. These checkpoints,
and the procedure of the merge, are detailed in this document.

__Bert-E__ and your pull request
--------------------------------
__Here we give an eagle view on how *Bert-E* will interact with a pull request.
Keep reading to get more insights on specific points.__

__Bert-E__ can only merge the code if a set of rules is respected on branches
and associated tickets. __Bert-E__ helps the participants in a pull request
correct the items that do not follow the rules, by issuing a status report and
specific messages.

* There are different stages in the merge of a pull request

    * verification that the minimum information required for the process is
      correct
    * creation of temporary integration branches in the repository
    * verification that the author and the reviewers of the pull request agree
      for the merge, and verification of the build status
    * merge on all destination branches

* The rules to progress to the **creation of the integration branches** are

    * the destination branch must be a _development/..._
    * the source branch must have a prefix that is valid for the destination
      branch
    * the branch name must contain a valid Jira ticket (on the corresponding
      project)
    * check that the Fix Version/s field in the Jira ticket is coherent (can be
      deactivated by configuration of Bert-E)
    * the diff introduced by the branch is less than 1000 lines

* The rules to progress to the **final merge** are, in addition to the rules
  above

    * check that all conflicts have been resolved
    * check that reviewers have approved the pull request
    * check that the author has approved the pull request (skipped on GitHub)
    * check that the build status is green

Comments
--------
__*Bert-E* interacts with the author and participants in a pull request via
comments.__

When something is bothering __Bert-E__, he will try to help the developer
resolve the matter by adding a comment in the pull request. __Bert-E__ will
then wait, and will re-analyse the pull request once it is updated. If the
problem is still present, nothing will happen. If the problem is resolved,
__Bert-E__ will proceed to the next step towards the merge.

__Bert-E__ includes a message-code and the active options in the footer of the
message. This is useful to send this information to the admin team when
you want to raise an issue with us.

    **Example: Greetings message**

    Hello <author name>,

    My name is __Bert-E__. My role is to assist you with the merge of this pull
    request. Please type @bert-e help to get information on this process.

    There are currently no active options. Type @bert-e help to obtain the list.

Options
-------
__The behaviour of *Bert-E* can be customised to fit the needs
of each specific pull requests.__

In order to activate an option for a pull request, address a comment at
@bert-e, including the labels of the required options. The option remains valid
as long as the comment remains present in the pull request. To deactivate an
option, delete the related comment!

Some options require special privileges. Only a predefined list of users can
activate these options (namely, the 'admins' of the development branches of
that project). If such an option is required on a pull request, please include
a member of the admin team as a reviewer.

To obtain the list of existing options, send the following command to
__Bert-E__:

    @bert-e help

The active options will also be reminded in the footer each message sent by
__Bert-E__.

| options name              | description              | requires admin rights? | requires pull request author? |
|:------------------------- |:------------------------ |:----------------------:|:-----------------------------:|
| after_pull_request        | Wait for the given pull request id to be merged before continuing with the current one. May be used like this: @bert-e after_pull_request=< pr_id_1 > ... | no | no
| bypass_author_approval    | Bypass the pull request author's approval   | yes | no
| bypass_build_status       | Bypass the build and test status| yes | no
| bypass_incompatible_branch | Bypass the check on the source branch prefix | yes | no
| bypass_jira_check         | Bypass the Jira issue check | yes | no
| bypass_peer_approval      | Bypass the pull request peer's approval | yes | no
| bypass_leader_approval    | Bypass the pull request leader's approval | yes | no
| create_pull_requests      | Let __Bert-E__ create pull requests corresponding to integration branches | no | no
| create_integration_branches | Request __Bert-E__ to create integration branches and move forward with the gitwaterflow | no | no
| no_octopus                | Prevent Wall-E from doing any octopus merge and use multiple consecutive merge instead | yes | no
| unanimity                 | Change review acceptance criteria from `one reviewer at least` to `all reviewers` (**this feature is not supported on GitHub**) | no | no
| wait                      | Instruct __Bert-E__ not to run until further notice | no | no
| approve                   | Tells __Bert-E__ that the author approves the PR | no | yes

> **Example: Unanimity option**
>
> By default, __Bert-E__ only needs one reviewer to consider the code is valid.
> But the author of the pull request wishes to get the approval of all
> reviewers before merging the code.
>
> To activate the option 'unanimity', the author of the pull request (or any
> other participant), can address the following comment at __Bert-E__:
>
> @bert-e unanimity
>
> If later, the developer changes his mind, and believes only one reviewer is
> enough, he/she should delete his/her comment.

(option available in __Bert-E__ >= 1.0.1)

Commands
--------
__It is possible to instruct *Bert-E* to operate some one-time operations on
your pull requests.__

These are called commands. The mechanism behind commands is similar to options,
with the only difference being that once the command has been executed,
__Bert-E__ will ignore the comment that contains it.

To obtain the list of existing commands, send the following command to
__Bert-E__:

    @bert-e help

| command name          | description              | requires admin rights? |
|:--------------------- |:------------------------ |:----------------------:|
| help                  | Print __Bert-E__'s manual in the pull request | no
| reset                 | Let __Bert-E__ reset the integration branches associated to the current pull request with a warning if the developer manually modified one of the the integration branches | no
| force_reset           | Let __Bert-E__ reset the integration branches associated to the current pull request **without warning**. | no

Integration branches...
-----------------------
__*Bert-E* creates temporary branches during the merge process. These are
called integration branches.__

The latest code from the pull request is merged with the latest code from the
target development branch. This code is then tested in the build pipeline,
before any merge can happen. There are as many integration branches as there
are target branches.

The integration branches are mandatory in the GitWaterFlow process,
and by default they are automatically created when a pull request is
opened.
This behaviour can be changed with the `always_create_integration_branches`
parameter in the bot settings:

* *true* (default): integration branches are created automatically when a
  pull request is opened.
* *false*: users will be required to explicitly request the creation
  of integration branches by adding a `/create_integration_branches`
  comment in their pull request (or it will be set for them during
  other operations, like `approve` or `create_pull_requests`).

On the Git project, the name of the integration branches follow the format:

```w/<version>/<name_of_source_branch>```

where:

* *version*: the version of the target _development/..._ branch
* *name_of_source_branch*: the name of the source branch (for example:
  feature/KEY-12345, bugfix/KEY-12345)

...and Integration pull requests
--------------------------------
__*Bert-E* can also create pull requests associated with each
integration branches. These are called integration pull requests.__

In order to save on the bandwitdh of the API of some githost providers,
the creation of integration pull requests can be made optional. The
repository level setting __always_create_integration_pull_requests__ can be set
to:

* *True* (default): integration pull requests are always created,
* *False*: integration pull requests are created only when requested by
  the author or a reviewer

> The creation of integration pull requests can be requested manually by setting
> the __create_pull_requests__ option (__Bert-E__ >= 3.1.9).

When Bert-E creates the integration pull requests, the owner is __Bert-E__ and
there are no reviewers. The author and/or reviewers of the original pull
request can follow the new pull requests if they wish to be informed on
updates.

The title of an integration pull request follows this format:

    INTEGRATION [PR#:<id> > <branch>] <title>

where:

* *id*: the id of the parent pull request branch: the name of the target
  development branch
* *title*: the title of the original pull request

> Integration pull requests is a graphical place where you can check that the
> code that will end up in the development branches is correct and what you
> would expect!

Conditions to merge a pull request
----------------------------------
__Bert-E__ does a number of checks before merging some code; some of the checks
can be bypassed by setting an option.

The checks are done every time __Bert-E__ wakes up on a pull request.
__Bert-E__ stops processing the pull request as soon as a non conformance is
detected. The checks are the following, in this order:


**The pull request is OPEN.**
_Nothing particular happens otherwise._

---

**The destination branch is one that __Bert-E__ handles.**
__Bert-E__ ignore the pull request if the prefix of the target branch is not
_development/..._.

*Nothing particular happens otherwise.*

___

**The source branch is one that __Bert-E__ handles.**
__Bert-E__ will ignore the pull request if the source branch is prefixed
_hotfix/..._ or _user/..._.

*Nothing particular happens otherwise.*

___

**The prefix of the source branch is correct.**
__Bert-E__ will only accept the prefixes as defined for the project (the
list of valid prefixes varies from project to project, but typically
includes: _feature/..._, _bugfix/..._, _improvement/..._.

*__Bert-E__ sends message code 105 in case of non-conformance.*

___

**The prefix of the source branch is compatible with the destination branch.**
__Bert-E__ prevents the merge of a feature in a maintenance branch (only
bugfixes and improvements branches are accepted).

*__Bert-E__ sends message code 106 in case of non-conformance.*

> This check can be bypassed by an admin with the
> __bypass_incompatible_branch__ option (__Bert-E__ >= 1.0.1).

---

**The source branch name contains a JIRA ticket reference if required on the
destination branches.**
The ticket id must follow the prefix, for example feature/KEY-1234-xxx.

It is possible to use a ticketless branch on the current development branch
(most recent branch, currently: 6.0).

*__Bert-E__ sends message code 107 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_jira_check__ option.

---

**The JIRA issue exists.**
Note: It is possible to use a ticketless branch on the current development
branch.

*__Bert-E__ sends message code 108 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_jira_check__ option.

---

**The JIRA issue project corresponds to the GIT repository.**

*__Bert-E__ sends message code 110 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_jira_check__ option.

---

**The JIRA issue is not a subtask.**
It is not possible to merge the work of a subtask directly on _development/..._
branches, because subtasks are short-lived, and do not have attributes such as
fix versions. Subtasks should be merged in parent branches (the branches that
solve epics, user stories or bugfixes) instead, and these branches, in turn,
merged to _development/..._ branches.

*__Bert-E__ sends message code 109 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_jira_check__ option.

---

**The type of the JIRA issue matches the prefix of the source branch.**
There is a correspondance between the type of JIRA issue and the prefix to use
for the source branch name. The correspondance table is defined per project. A
typical correspondance table is:

* Issue type *User Story* → branch prefix *feature*,
* Issue type *Bug* → branch prefix *bugfix*,
* Issue type *Improvement* → branch prefix *improvement*.

This check is done in order to improve the clarity in the branch naming and the
coherence between JIRA and Bitbucket.

*__Bert-E__ sends message code 111 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_jira_check__ option.

---

**The 'Fix Version' list documented in the JIRA ticket matches the list of
destination branches.**
The fix version documented in JIRA is used for the generation of reports and
release notes. It is therefore important that this information is correct.

*__Bert-E__ sends message code 112 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_jira_check__ option.
> This check can also be permanently deactivated through Bert-E's configuration.

---

**At this point, __Bert-E__ creates the integration branches.**

---

**Check for any conflict on integration branches.**
Integration branches are created by merging the work done in the source branch
with the work already merged in the _development/..._ branches. Conflicts may
arise, in which case __Bert-E__ will inform the pull request participants, and
ask for manual resolution of the problem.

*__Bert-E__ sends message code 114 in case of conflict.*

*__Bert-E__ sends message code 113 in case the integration branches contain
unknown commits, following a rebase or other events on the source branch.*

---

**At this point, __Bert-E__ proceeds with the creation of integration pull
requests (optional) and runs the following checks.**

---

**The author has approved the pull request.**
This check ensures that the branch is not merged before the developer has
finished taking into account all the reviewer's comments and has double-checked
all the integration pull requests (optional).

*__Bert-E__ sends message code 115 in case of non-conformance.*

This check can be bypassed by an admin with the __bypass_author_approval__
option.

---

**Peers have approved the pull request.**
No code should go on _development/..._ branches without a proper review.
__Bert-E__ will verify this is the case by checking that a number of peers
have approved the code. Each peer is typically in charge of checking that:

* the code is correct and complete,
* the code is documented, internally and externally,
* the changes respond to the problematic of the corresponding JIRA ticket,
* the JIRA ticket is complete and correct,
* tests have been written to check the changes,
* tests have run at least once and passed.

The number of required leader approvals is a per repository setting
(the default being 2)

*__Bert-E__ sends message code 115 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_peer_approval__
> option.

---

**Project leaders have approved the pull request.**
In case project leaders have been defined in __Bert-E__'s configuration, each
pull request will need the approval of one or more leaders before __Bert-E__
accepts to merge the work. The number of required leader approvals is also
a per repository setting (the default being none).

*__Bert-E__ sends message code 115 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_leader_approval__
> option.

---

**The code on the integration branches has passed the build.**
The build pipeline is launched automatically on each integration branches. A
green light on all integration branches is mandatory before a merge can happen.

*__Bert-E__ sends message code 118 in case of non-conformance.*

> This check can be bypassed by an admin with the __bypass_build_status__
> option.

---

**At this point, __Bert-E__ adds the pull-request into the merge queue. Each
integration branch is merged into a queue branch that is being currently
built.**

---

**All commits in the queue branches, that integrate the pull-requests changes,
or all commits of a subsequent queued pull-request have passed.**
__Bert-E__ is waken up, analyses the queue branches, finds out that there is a
collection of commits (M) on these branches coming from the same pull-request,
that have all been successfully built. __Bert-E__ fast-forward the development
branches to these commits, which results on all pull-requests up to M in the
queue being merged and closed. __Bert-E__ notifies all of these pull-requests
that they have been merged.

Return codes and how to progress to the next step
-------------------------------------------------
__Bert-E__ interacts with a pull requests by sending messages when an action is
required. The content of the message aims at giving enough information to help
the owner resolve the situation and progress to the next stage of the
integration of his work.

The table below lists all possible return codes from __Bert-E__, the
corresponding message, and some additional information on the actions to take
to progress to the next step.  message code

| title | explanation | what to do |
|:----- |:----------- |:-----------|
| 100   | Hello | __Bert-E__ greets the owner to indicate that it will handle this pull request. If the message does not appear, __Bert-E__ will not be involved in the merge. No action required
| 102   | Successful merge | __Bert-E__ has succesfully merged the codeset in all targetted development branches. No action required
| 103   | Not implemented | __Bert-E__ has received a command, but this command is not implemented yet. No action required
| 106   | Incompatible branch type | The source branch cannot be merged in the destination branch. For example, it is not possible to merge new features in a maintenance branch. Decline the pull request, rename the source branch, and start a new pull request afresh or, request a bypass to an administrator of the repository
| 107   | Missing Jira issue | __Bert-E__ could not parse a JIRA ticket in the source branch name decline the pull request, rename the source branch, and start a new pull request afresh or, request a bypass to an administrator of the repository
| 108   | Jira issue not found | The JIRA ticket in the source branch name does not exist. Decline the pull request, rename the source branch, and start a new pull request afresh or, request a bypass to an administrator of the repository
| 109   | Cannot merge a subtask | The JIRA ticket in the source branch name corresponds to a sub-task in Jira. Decline the pull request, rename the source branch, and start a new pull request afresh or, request a bypass to an administrator of the repository
| 110   | Incorrect Jira project | The JIRA ticket in the source branch name does not match the repository. Decline the pull request, rename the source branch, and start a new pull request afresh or, request a bypass to an administrator of the repository
| 111   | Issue type vs branch prefix mismatch | The type of the JIRA ticket does not match the prefix of the source branch. Fix the type of the JIRA ticket to match the prefix or, decline the pull request, rename the source branch, and start a new pull request afresh or, request a bypass to an administrator of the repository
| 112   | Incorrect fix version | The fix version in the JIRA ticket does not match the destination branch. Update the fix versions in the ticket, then comment the pull request
| 113   | History mismatch | The integration branches contain some commits that are neither on the source or destination branches. Update the integration branches manually or delete them to restart the process
| 114   | Conflict | It is not possible to automatically merge the work from the pull request to all destination branches. Update the integration branches manually
| 115   | Waiting for approvals | Some approvals are missing. The author, peers and project leaders should approve the work submitted in the pull request. Alternatively, an administrator can bypass the approvals. The number of peers and leaders that must approve the work are defined in Bert-E's configuration for the repository. In case Unanimity option has been set, all of the participants in the pull request should approve the work, in addition to the previously mentionned requirements.
| 118   | Build failed | A build has failed on one of the integrations branches. In this situation, commenting the pull request has no effect (in most cases). Analyse the reason for the build failure. If the failure is due to your changes: fix the problem push the new code on the same branch; If the failure is due to an instability of the pipeline or a failure of the build environement: log the problem in JIRA (or update an existing ticket with the link to the new failure) launch a new build on your branch. Commenting the pull request only may work, but only in the case where some other code has been merged in the destination branches. In this case, __Bert-E__ will merge the new code in the integration branches, which will trigger new builds. You should not count on this behaviour however, unless you know for sure that another pull request was merged since the last build report.
| 120   | After pull request | The after_pull_request option has been activated, and the target pull request is not merged yet work on merging the pending pull request or remove the option
| 121   | Integration data created | __Bert-E__ notifies the owner that he succesfully created the integration branches and the related pull requests, and provides a link to them. No action required
| 122   | Unknown command | One of the participants asked __Bert-E__ to activate an option, or execute a command he doesn't know. Edit the corresponding message if it contains a typo. Delete it otherwise
| 123   | Not authorized | One of the participants asked __Bert-E__ to activate a privileged option, or execute a privileged command, but doesn't have enough credentials to do so. Delete the corresponding command ask a __Bert-E__ administrator to run/set the desired command/option.
| 134   | Not author | One of the participants asked __Bert-E__ to activate an authored option, but the participant is not the author of the pull request.

Queues
------

Bert-E's queue is a mechanism to stack and merge pull requests
that have passed all the [conditions to merge](#conditions-to-merge-a-pull-request).

When multiple people are working on the same repository, there
will be multiple pull requests opened, each of them at
different stages of meeting the conditions set by the bot.
Therefore when the conditions are met, they will not contain
the latest commits that are included in the destination branch.

Bert-E will proceed in taking the pull request forward by merging it into
the queue branches.

Each development/x.y branch will have its according `q/x.y` branch, and
each PR in the queue will also have its according `q/$PR_ID/x.y/$BRANCH_NAME` branch.

For a PR that is in the queue to be merged into the development branch,
a green build is required. Depending on the state of the queue or how many
branches there are, the green build can be located at different places (refer
to the scenarios for more information).

Multiple PRs can be stacked into the queue and
Bert-E will proceed in merging them either partially or as a whole package
depending on the state of it.

Following here a couple of scenarios of
queue state and the behavior we can expect from Bert-E.

> On all the scenarios below PR #42 will be the first to enter the queue, followed
by PR #43 and PR #44.
Bert-E will always sort the queue table view by order in which each PR got queued,
the first line will be the first PR that got in, and the latest PR will be at the end.

### Scenario 1

| PR/Branches |        q/1.0       |        q/2.0       |        q/3.0       |
|:-----------:|:------------------:|:------------------:|:------------------:|
|     #42     | :heavy_check_mark: | :heavy_check_mark: |         :x:        |
|     #43     | :heavy_check_mark: | :heavy_check_mark: |         :x:        |
|     #44     | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |

All PRs will be merged as #44 is the latest PR to enter the queue,
it contains the code from both #42 and #43 and
all the builds are green.
At this point, we don't really care why some builds failed on `q/3.0`. It could be a flaky build (because of the code or because of the env) or even an incompatibility of the merging code with the destination branch. As long as we have a green build, we can ignore what's above.


### Scenario 2

| PR/Branches |        q/1.0       |        q/2.0       |        q/3.0       |
|:-----------:|:------------------:|:------------------:|:------------------:|
|     #42     | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
|     #43     | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
|     #44     | :heavy_check_mark: | :heavy_check_mark: |      :clock2:      |

Only #42 and #43 will be merged as they both have all the queue branches with
green builds. #44 still have one build pending, Bert-E will wait for the
result of this build before taking any further actions on #44.

### Scenario 3

| PR/Branches |        q/1.0       |        q/2.0       |        q/3.0       |
|:-----------:|:------------------:|:------------------:|:------------------:|
|     #42     |         :x:        | :heavy_check_mark: | :heavy_check_mark: |
|     #43     | :heavy_check_mark: |         :x:        | :heavy_check_mark: |
|     #44     | :heavy_check_mark: | :heavy_check_mark: |         :x:        |

No PR will be merged as they each have a failed build on a specific branch.

> Note: to merge the queue above, the only build to succeed is `q/3.0` for #44.
Refer to scenario 1 for more information.

All those states can be found on Bert-E's UI.

> Note: Bert-E will not notify the user if a build
fails inside the queue.

Going further with __Bert-E__
-----------------------------
Do you like __Bert-E__? Would like to use it on your own projects?

There are great robots around the world that have more or less the same job as
__Bert-E__ (Zuul being one that springs to mind). Some of these robots may even
be brighter (predictive merges and co). We decided to develop __Bert-E__
because none had some of the specificities we needed. __Bert-E__ will continue
to grow, and get inspired by his bigger brothers.  __Bert-E__, the free robot?
