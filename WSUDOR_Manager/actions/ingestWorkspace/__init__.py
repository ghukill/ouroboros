# utility for Bag Ingest

# celery
from cl.cl import celery

# handles
from WSUDOR_Manager.forms import RDF_edit
from WSUDOR_Manager.solrHandles import solr_handle
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager import redisHandles, jobs, models, db, forms, models
import WSUDOR_Manager.actions as actions
import WSUDOR_ContentTypes
try:
	import ouroboros_assets
except:
	print "could not load git submodule 'ouroboros_assets'"
import localConfig

from flask import Blueprint, render_template, abort, request, redirect, session, jsonify

#python modules
from lxml import etree
import re
import json
import os
import tarfile
import uuid
from string import upper
import xmltodict
import requests
import time
import traceback
import subprocess

# eulfedora
import eulfedora

# import bagit
import bagit

# flask-SQLalchemy-datatables
from datatables import ColumnDT, DataTables

# create blueprint
ingestWorkspace = Blueprint('ingestWorkspace', __name__, template_folder='templates', static_folder="static")


#################################################################################
# Routes
#################################################################################

# main view
@ingestWorkspace.route('/ingestWorkspace', methods=['POST', 'GET'])
def index():

	# get all jobs
	ijs = models.ingest_workspace_job.query.all()

	return render_template("ingestWorkspace.html", ijs=ijs)


# job edit / view
@ingestWorkspace.route('/ingestWorkspace/job/<job_id>', methods=['POST', 'GET'])
def job(job_id):

	# get handle
	j = models.ingest_workspace_job.query.filter_by(id=job_id).first()	

	# render
	return render_template("ingestJob.html", j=j, localConfig=localConfig, ouroboros_assets=ouroboros_assets)


# job delete
@ingestWorkspace.route('/ingestWorkspace/job/<job_id>/delete', methods=['POST', 'GET'])
def deleteJob(job_id):

	'''
	Consider removing directory as well...
	'''

	# clean job
	print "removing job"
	j = models.ingest_workspace_job.query.filter_by(id=job_id).first()
	j._delete()

	# clean object
	print "removing associated objects with job"
	jos = models.ingest_workspace_object.query.filter_by(job_id=job_id)
	for o in jos:		
		o._delete()
	db.session.commit()

	return redirect('/%s/tasks/ingestWorkspace' % localConfig.APP_PREFIX)



# job edit / view
@ingestWorkspace.route('/ingestWorkspace/createJob', methods=['POST', 'GET'])
def createJob():

	# render
	return render_template("createJob.html")



# job edit / view
@ingestWorkspace.route('/ingestWorkspace/objectDetails/<job_id>/<ingest_id>', methods=['POST', 'GET'])
def objectDetails(job_id,ingest_id):

	'''
	Render out metadata components for an object for viewing and debugging
	'''	

	# get object handle from DB
	o = models.ingest_workspace_object.query.filter_by(job_id=job_id,ingest_id=ingest_id).first()
	
	# attempt directory listing of bag_path
	if o.bag_path != None:
		bag_tree = subprocess.check_output(['tree',o.bag_path])
		bag_tree = bag_tree.decode('utf-8')
	else:
		bag_tree = False	

	# render
	return render_template("objectDetails.html",o=o,bag_tree=bag_tree)



#################################################################################
# Datatables Endpoint
#################################################################################

# return json for job
@ingestWorkspace.route('/ingestWorkspace/job/<job_id>.json', methods=['POST', 'GET'])
def jobjson(job_id):	

	def exists(input):
		if input != None:
			return "<span style='color:green;'>True</span>"
		else:
			return "<span style='color:red;'>False</span>"

	def boolean(input):		
		if input == "1":
			return "<span style='color:green;'>True</span>"
		else:
			return "<span style='color:red;'>False</span>"
	
	# defining columns
	columns = []	
	columns.append(ColumnDT('ingest_id'))
	columns.append(ColumnDT('object_title'))
	columns.append(ColumnDT('pid'))
	columns.append(ColumnDT('object_type'))
	columns.append(ColumnDT('DMDID'))	
	columns.append(ColumnDT('struct_map', filter=exists))
	columns.append(ColumnDT('MODS', filter=exists))
	columns.append(ColumnDT('bag_path'))
	columns.append(ColumnDT('objMeta', filter=exists))
	columns.append(ColumnDT('ingested', filter=boolean))
	columns.append(ColumnDT('repository'))


	# defining the initial query depending on your purpose
	query = db.session.query(models.ingest_workspace_object).filter(models.ingest_workspace_object.job_id == job_id)

	# instantiating a DataTable for the query and table needed
	rowTable = DataTables(request.args, models.ingest_workspace_object, query, columns)

	# returns what is needed by DataTable
	return jsonify(rowTable.output_result())


#################################################################################
# View SQL row data
#################################################################################
@ingestWorkspace.route('/ingestWorkspace/viewSQLData/<table>/<id>/<column>/<mimetype>', methods=['POST', 'GET'])
def viewSQLData(table,id,column,mimetype):
	return "Coming soon"



#################################################################################
# Create Ingest Job
#################################################################################

@celery.task(name="createJob_factory")
def createJob_factory(job_package):
	
	print "FIRING createJob_factory"

	# get form data
	form_data = job_package['form_data']	

	# set new task_name, for the worker below
	job_package['custom_task_name'] = 'createJob_worker'	

	# get ingest metadata
	if 'upload_data' in job_package:		
		ingest_metadata = job_package['upload_data']
	elif form_data['pasted_metadata'] != '':
		ingest_metadata = form_data['pasted_metadata'] 
	
	# initiate ingest job instance with name
	j = models.ingest_workspace_job(form_data['collection_identifier'])	

	# add metadata
	j.ingest_metadata = ingest_metadata	

	# set final ingest job values, and commit, add job number to job_package
	j._commit()
	job_package['job_id'] = j.id
	job_package['job_name'] = j.name

	# for each section of METS, break into chunks
	XMLroot = etree.fromstring(ingest_metadata)
	
	# grab stucture map
	sm = XMLroot.find('{http://www.loc.gov/METS/}structMap')
	collection_level_div = sm.find('{http://www.loc.gov/METS/}div')

	# update job with collection level DMDID (used throughout as collection identifier)
	j.identifier = collection_level_div.attrib['DMDID']
	j._commit()
	
	# iterate through, ignoring comments
	sm_parts = [element for element in collection_level_div.getchildren() if type(element) != etree._Comment]

	# add collection object to front of list
	sm_parts.insert(0,collection_level_div)

	# pop METS ingest from job_package	
	if 'upload_data' in job_package:
		job_package['upload_data'] = ''
	elif 'pasted_metadata' in form_data:
		job_package['form_data']['pasted_metadata'] = ''

	# update job info (need length from above)
	redisHandles.r_job_handle.set("job_%s_est_count" % (job_package['job_num']), len(sm_parts))

	# insert into MySQL as ingest_workspace_object rows
	step = 1
	
	# iterate through and add components
	for i,sm_part in enumerate(sm_parts):
		
		print "Creating ingest_workspace_object row %s / %s" % (step, len(sm_parts))
		job_package['step'] = step

		# set internal id (used for selecting when making bags and ingesting)
		job_package['ingest_id'] = step

		# set type
		if i == 0:
			job_package['object_type'] = "collection"
		else:
			job_package['object_type'] = "component"

		# attempt to fire worker
		try:
			
			# get DMDID
			job_package['DMDID'] = sm_part.attrib['DMDID']
			job_package['object_title'] = sm_part.attrib['LABEL']
			
			print "StructMap part ID: %s" % job_package['DMDID']

			# store structMap section as python dictionary
			sm_dict = xmltodict.parse(etree.tostring(sm_part))
			job_package['struct_map'] = json.dumps(sm_dict)

			# grab descriptive mets:dmdSec
			dmd_handle = XMLroot.xpath("//mets:dmdSec[@ID='%s']" % (sm_part.attrib['DMDID']), namespaces={'mets':'http://www.loc.gov/METS/'})[0]
			# grab MODS record and write to temp file		
			MODS_elem = dmd_handle.find('{http://www.loc.gov/METS/}mdWrap[@MDTYPE="MODS"]/{http://www.loc.gov/METS/}xmlData/{http://www.loc.gov/mods/v3}mods')
			temp_filename = "/tmp/Ouroboros/"+str(uuid.uuid4())+".xml"
			fhand = open(temp_filename,'w')
			fhand.write(etree.tostring(MODS_elem))
			fhand.close()		
			job_package['MODS_temp_filename'] = temp_filename

		except:
			print "ERROR"
			print traceback.print_exc()

		# fire task via custom_loop_taskWrapper			
		result = actions.actions.custom_loop_taskWrapper.delay(job_package)
		task_id = result.id

		# Set handle in Redis
		redisHandles.r_job_handle.set("%s" % (task_id), "FIRED,%s" % (job_package['DMDID']))
			
		# update incrementer for total assigned
		jobs.jobUpdateAssignedCount(job_package['job_num'])

		# bump step
		step += 1



@celery.task(name="createJob_worker")
def createJob_worker(job_package):

	print job_package.keys()
	print "Adding ingest_workspace_object for %s / %s" % (job_package['DMDID'],job_package['object_title'])

	# open instance of job
	j = models.ingest_workspace_job.query.filter_by(id=job_package['job_id']).first()

	# instatitate object instance
	o = models.ingest_workspace_object(j, object_title=job_package['object_title'], DMDID=job_package['DMDID'])

	# set type
	o.object_type = job_package['object_type']

	# fill out object row with information from job_package
	o.ingest_id = job_package['ingest_id']

	# structMap
	o.struct_map = job_package['struct_map']

	# MODS file
	if job_package['MODS_temp_filename']:
		with open(job_package['MODS_temp_filename'], 'r') as fhand:
			o.MODS = fhand.read()
			os.remove(job_package['MODS_temp_filename'])
	else:
		o.MODS = None

	# add and commit(for now)
	return o._commit()


#################################################################################
# Create Bag 
#################################################################################

@celery.task(name="createBag_factory")
def createBag_factory(job_package):
	
	print "FIRING createBag_factory"
	
	# DEBUG
	print job_package

	# get form data
	form_data = job_package['form_data']	

	# set bag dir
	bag_dir = '/tmp/Ouroboros/ingest_jobs/ingest_job_%s' % (form_data['job_id'])
	job_package['bag_dir'] = bag_dir
	if not os.path.exists(bag_dir):
		os.mkdir(bag_dir)

	# set new task_name, for the worker below
	job_package['custom_task_name'] = 'createBag_worker'

	# parse object rows from range (use parseIntSet() above)
	object_rows = parseIntSet(nputstr=form_data['object_id_range'])

	# update job info (need length from above)
	redisHandles.r_job_handle.set("job_%s_est_count" % (job_package['job_num']), len(object_rows))
	
	# insert into MySQL as ingest_workspace_object rows
	step = 1
	time.sleep(2)
	for row in object_rows:

		print "Creating bag for ingest_id: %s, count %s / %s" % (row, step, len(object_rows))
		job_package['step'] = step

		# set row
		job_package['ingest_id'] = row
		job_package['job_id'] = form_data['job_id']
		
		result = actions.actions.custom_loop_taskWrapper.delay(job_package)
		task_id = result.id

		# Set handle in Redis
		redisHandles.r_job_handle.set("%s" % (task_id), "FIRED,%s" % (step))
			
		# update incrementer for total assigned
		jobs.jobUpdateAssignedCount(job_package['job_num'])

		# bump step
		step += 1
	


@celery.task(name="createBag_worker")
def createBag_worker(job_package):

	print "FIRING createBag_worker"

	# DEBUG
	print job_package

	# get form data
	form_data = job_package['form_data']

	# determine if purging old bags
	if 'purge_bags' in form_data and form_data['purge_bags'] == 'on':
		purge_bags = True
	else:
		purge_bags = False

	# get object row
	o = models.ingest_workspace_object.query.filter_by(ingest_id=job_package['ingest_id'],job_id=job_package['job_id']).first()
	print "Working on: %s" % o.object_title

	# GET JOB HERE AND ADD AS collection_identifier

	# load bag class
	print "loading bag class for %s" % form_data['bag_creation_class']	
	bag_class_handle = getattr(ouroboros_assets.bag_classes, form_data['bag_creation_class'])

	# load collection class (if needed)
	collection_class_handle = getattr(ouroboros_assets.bag_classes, 'collection_object')

	# load MODS as etree element
	try:
		MODS_root = etree.fromstring(o.MODS)	
		ns = MODS_root.nsmap
		MODS_handle = {
			"MODS_element" : MODS_root.xpath('//mods:mods', namespaces=ns)[0],
			"MODS_ns" : ns
		}
	except:
		print "could not load MODS as etree element"

	# if not purging bags, and previous bag_path already found, skip
	if purge_bags == False and o.bag_path != None:
		print "skipping bag creation for %s / %s, already exists" % (o.object_title,o.DMDID)
		bag_result = False

	# else, create bags (either overwriting or creating new)
	else:
		# instantiate bag_class_worker from class
		if o.object_type == 'collection':
			print "firing collection object bag creator"
			class_handle = collection_class_handle
		else:
			class_handle = bag_class_handle

		bag_class_worker = class_handle.BagClass(
			object_row = o,
			ObjMeta = models.ObjMeta,
			bag_root_dir = job_package['bag_dir'],
			files_location = form_data['files_location'],
			MODS = o.MODS,
			MODS_handle = MODS_handle,
			struct_map = o.struct_map,
			object_title = o.object_title,
			DMDID = o.DMDID,
			collection_identifier = o.job.identifier,
			purge_bags = purge_bags
		)

		bag_result = bag_class_worker.createBag()


	# finish up with updated values from bag_class_worker

	# write some data back to DB
	if purge_bags == True:
		# remove previously recorded and stored bag
		os.system("rm -r %s" % o.bag_path)
	# sets, or updates, the bag path
	o.bag_path = bag_class_worker.obj_dir

	# set objMeta
	o.objMeta = bag_class_worker.objMeta_handle.toJSON()

	# set PID
	o.pid = bag_class_worker.pid

	# commit
	bag_class_worker.object_row._commit()
	

	return bag_result	



#################################################################################
# Ingest Bag 
#################################################################################

@celery.task(name="ingestBag_factory")
def ingestBag_factory(job_package):
	
	'''
	offloads to actions/bagIngest.bagIngest_worker()
	'''

	print "FIRING ingestBag_factory"
	
	# DEBUG
	print job_package

	# get form data
	form_data = job_package['form_data']	

	# set new task_name, for the worker below
	job_package['custom_task_name'] = 'bagIngest_worker'

	# parse object rows from range (use parseIntSet() above)
	object_rows = parseIntSet(nputstr=form_data['object_id_range'])

	# update job info (need length from above)
	redisHandles.r_job_handle.set("job_%s_est_count" % (job_package['job_num']), len(object_rows))
	
	# insert into MySQL as ingest_workspace_object rows
	step = 1
	time.sleep(2)
	for row in object_rows:

		print "Creating bag for ingest_id: %s, count %s / %s" % (row, step, len(object_rows))
		job_package['step'] = step

		# set row
		job_package['ingest_id'] = row
		job_package['job_id'] = form_data['job_id']

		# open row, get currently held bag_dir
		o = models.ingest_workspace_object.query.filter_by(ingest_id=job_package['ingest_id'],job_id=job_package['job_id']).first()
		if o.bag_path != None:
			job_package['bag_dir'] = o.bag_path
		else:
			job_package['bag_dir'] = False
		
		result = actions.actions.custom_loop_taskWrapper.delay(job_package)
		task_id = result.id

		# Set handle in Redis
		redisHandles.r_job_handle.set("%s" % (task_id), "FIRED,%s" % (step))
			
		# update incrementer for total assigned
		jobs.jobUpdateAssignedCount(job_package['job_num'])

		# bump step
		step += 1


@celery.task(name="ingestBag_callback")
def ingestBag_callback(job_package):
	
	print "FIRING ingestBag_callback"

	# DEBUG
	print job_package

	# open handle
	o = models.ingest_workspace_object.query.filter_by(ingest_id=job_package['ingest_id'],job_id=job_package['job_id']).first()
	print "Retrieved row: %s / %s" % (o.ingest_id,o.object_title)
	print "Setting ingest to True"
	o.ingested = True
	return o._commit()



#################################################################################
# Utilities
#################################################################################

def parseIntSet(nputstr=""):
	selection = set()
	invalid = set()
	# tokens are comma seperated values
	tokens = [x.strip() for x in nputstr.split(',')]
	for i in tokens:
		if len(i) > 0:
			if i[:1] == "<":
				i = "1-%s"%(i[1:])
		try:
			# typically tokens are plain old integers
			selection.add(int(i))
		except:
			# if not, then it might be a range
			try:
				token = [int(k.strip()) for k in i.split('-')]
				if len(token) > 1:
					token.sort()
					# we have items seperated by a dash
					# try to build a valid range
					first = token[0]
					last = token[len(token)-1]
					for x in range(first, last+1):
						selection.add(x)
			except:
				# not an int and not a range...
				invalid.add(i)
	# Report invalid tokens before returning valid selection
	if len(invalid) > 0:
		print "Invalid set: " + str(invalid)
	return selection

