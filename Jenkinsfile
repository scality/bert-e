#!groovy
import groovy.json.JsonSlurper
import groovy.json.JsonOutput


def repo_slug = "wall-e"
def build_status = 'SUCCESSFUL'
def git_commit = ''
def git_branch = ''
def short_commit = ''
has_pr_list = false


stage name: 'initialisation'
    node('master') {
        deleteDir() // remove all previous artifacts from workspace

        checkout([
            $class: 'GitSCM',
            branches: scm.branches,
            doGenerateSubmoduleConfigurations: scm.doGenerateSubmoduleConfigurations,
            extensions: scm.extensions + [[$class: 'CloneOption', noTags: false, reference: '/srv/git/wall-e.reference', shallow: true]],
            submoduleCfg: [],
            userRemoteConfigs: scm.userRemoteConfigs
        ])
        sh('git rev-parse HEAD > GIT_COMMIT')
        git_commit=readFile('GIT_COMMIT')
        short_commit=git_commit.take(6)
        git_branch=env.BRANCH_NAME

        stash name: 'repository'

        bitbucketNotify(repo_slug, git_branch, short_commit,
                        "build",
                        "pipeline", "${env.BUILD_URL}console",
                        "INPROGRESS", false)
    }


stage concurrency: 1, name: 'build'
    node('trusty-small') {
        unstash 'repository'

        try {
            withCredentials([[$class: 'UsernamePasswordMultiBinding',
                              credentialsId: 'wall-e',
                              passwordVariable: 'WALL_E_PASSWORD',
                              usernameVariable: 'WALL_E_USERNAME'
                             ],
                             [$class: 'UsernamePasswordMultiBinding',
                              credentialsId: 'tester-of-wall-e',
                              passwordVariable: 'TESTER_PASSWORD',
                              usernameVariable: 'TESTER_USERNAME'
                             ],
                             [$class: 'UsernamePasswordMultiBinding',
                              credentialsId: 'eva',
                              passwordVariable: 'EVA_PASSWORD',
                              usernameVariable: 'EVA_USERNAME'
                             ]]) {

                sh '''flake8 *.py'''

                sh '''python test_wall_e.py \\
                          -v \\
                          --repo-prefix _test_wall_e_jenkins \\
                          ${WALL_E_PASSWORD} \\
                          ${EVA_PASSWORD} \\
                          ${TESTER_USERNAME} \\
                          ${TESTER_PASSWORD} \\
                          sylvain.killian@scality.com'''
            }
        } catch (e) {
            build_status = 'FAILED'
        }
    }


stage name: 'finalisation'
    node('master') {
        bitbucketNotify(repo_slug, git_branch, short_commit,
                        "build",
                        "pipeline", "${env.BUILD_URL}console",
                        build_status, true)

        if (build_status == 'FAILED') {
            currentBuild.result = 'FAILURE'
        }
    }
