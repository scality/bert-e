#!groovy

import groovy.json.JsonOutput

stage concurrency: 1, name: 'build'

node('small') {
    checkout scm

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

        sh '''python test_wall_e.py --repo-prefix _test_wall_e_jenkins \\
                  ${WALL_E_PASSWORD} \\
                  ${EVA_PASSWORD} \\
                  ${TESTER_USERNAME} \\
                  ${TESTER_PASSWORD} \\
                  sylvain.killian@scality.com'''
    }
}
