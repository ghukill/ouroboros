#!/usr/bin/env python
import requests
import json
import sys
import os
import datetime
import time
from collections import OrderedDict
from flask import Blueprint, render_template, redirect, abort, request
from flask.ext.login import login_required

import WSUDOR_ContentTypes
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager import celery, utilities, roles, redisHandles, jobs, logging
import WSUDOR_Manager.actions as actions

import localConfig


diagnostics = Blueprint('diagnostics', __name__, template_folder='templates', static_folder="static")


@diagnostics.route('/diagnostics', methods=['GET', 'POST'])
# @login_required
# @roles.auth(['admin','metadata'])
def index():	

	# render
	return render_template("diagnostics.html")



@diagnostics.route('/diagnostics/front_end_postman', methods=['GET', 'POST'])
# @login_required
# @roles.auth(['admin','metadata'])
def front_end_postman():	

	'''
	Form that configures and submits postman tests for running as background job
	'''

	# check for run reports
	reports = [f for f in os.listdir("/tmp/Ouroboros") if f.startswith('postman_report_')]

	# render
	return render_template("front_end_postman.html", reports=reports)


@celery.task(name="front_end_postman_factory")
def front_end_postman_factory(job_package):

	'''
	receives postman job to run	
	'''

	# get form data
	form_data = job_package['form_data']	

	# set new task_name, for the worker below
	job_package['custom_task_name'] = 'front_end_postman_worker'

	# update job info (need length from above)
	redisHandles.r_job_handle.set("job_%s_est_count" % (job_package['job_num']), 1)

	# fire task via custom_loop_taskWrapper			
	result = actions.actions.custom_loop_taskWrapper.apply_async(kwargs={'job_package':job_package}, queue=job_package['username'])
	task_id = result.id

	# Set handle in Redis
	redisHandles.r_job_handle.set("%s" % (task_id), "FIRED,%s" % (form_data['report_name']))
		
	# update incrementer for total assigned
	jobs.jobUpdateAssignedCount(job_package['job_num'])


@celery.task(name="front_end_postman_worker")
# @roles.auth(['admin','metadata'], is_celery=True)
def front_end_postman_worker(job_package):

	'''
	receives postman job to run	
	target command: newman run https://raw.githubusercontent.com/WSULib/ouroboros/v2/inc/postman/WSUDOR.postman_collection.json -e https://raw.githubusercontent.com/WSULib/ouroboros/v2/inc/postman/WSUDOR.postman_environment.json -r html --reporter-html-export /tmp/Ouroboros/postman_report_[REPORT_NAME].json
	'''

	# get form data
	form_data = job_package['form_data']	
	logging.debug("running postman front-end tests, report: %s" % form_data['report_name'])

	# run newman job, exports to /tmp/Ouroboros
	cmd = "newman run https://raw.githubusercontent.com/WSULib/ouroboros/v2/inc/postman/WSUDOR.postman_collection.json -e https://raw.githubusercontent.com/WSULib/ouroboros/v2/inc/postman/WSUDOR.postman_environment.json -r json --reporter-json-export /tmp/Ouroboros/postman_report_%s.json -n %s" % (form_data['report_name'],form_data['iterations'])
	os.system(cmd)

	# # open results
	'''
	Consider data parsing here?  If long, would make sense to do so here instead of page load for report view
	'''
	# time.sleep(1)
	# with open('/tmp/Ouroboros/postman_report_%s.json' % form_data['report_name']) as f:
	# 	report_json = json.loads(f.read())

	return json.dumps({
		"msg": "check for reports here: http://%s/%s/tasks/diagnostics/front_end_postman" % (localConfig.APP_HOST, localConfig.APP_PREFIX)
	})


@diagnostics.route('/diagnostics/front_end_postman/view_report/<report_name>', methods=['GET', 'POST'])
# @login_required
# @roles.auth(['admin','metadata'])
def front_end_postman_view(report_name):

	# load report
	logging.debug("loading /tmp/Ouroboros/%s" % report_name)
	with open('/tmp/Ouroboros/%s' % report_name) as f:
		report_json = json.loads(f.read())

	# data_payload
	data_payload = {}

	# parse results and prepare for graph
	executions = report_json['run']['executions']

	'''
	"executions" is a list of "tests"
	name = test['item']['name']
	responseTime = test['response']['responseTime']

	Need to sort these by name, then create a list of responseTimes associated with each name
	'''

	# sort tests and append to OrderedDictionary
	sorted_tests = OrderedDict()
	for test in executions:
		name = test['item']['name']
		responseTime = test['response']['responseTime']
		# if not in dictionary, add with name as key
		if test['item']['name'] not in sorted_tests.keys():
			logging.debug("adding %s" % name)
			sorted_tests[name] = {
				'name':name,
				'data':[]
			}
		# add responseTime to test dictionary
		sorted_tests[name]['data'].append(responseTime)
	# append each test
	data_payload['tests'] = [sorted_tests[test] for test in sorted_tests]

	# prep labels based on length first test data points
	data_payload['labels'] = ["n%s" % x for x in xrange(len(data_payload['tests'][0]['data']))]


	# DEBUG
	# import random
	# def randoData():		
	# 	return [int(random.random() * 1000) for x in xrange(7)]
	# data_payload = [ {'name':'test_line','data':randoData()} for x in xrange(10) ]


	# render
	return render_template("front_end_postman_view_report.html", data_payload=data_payload)
















