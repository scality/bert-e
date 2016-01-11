Commit #{{commit}} which belongs to the first integration branch
`{{integration_branch.name}}` does not come from the development branch
`{{development_branch.name}}` or from the feature branch
 `{{feature_branch.name}}`.

Either you have changed your feature branch history
(e.g. rebase) or you have directly commited on the first integration branch
`{{integration_branch.name}}`.

In either cases, I cannot merge until you delete all the related `w/*`
branches or rebase them if they contain useful commits.