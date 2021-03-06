# small utility to edit RELS-EXT datastream for objects

# handles
from WSUDOR_Manager.forms import RDF_edit
from WSUDOR_Manager.solrHandles import solr_handle
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager import jobs, models, db, utilities, roles, logging
from localConfig import *
from flask import Blueprint, render_template, abort, request
from flask.ext.login import login_required

#python modules
from lxml import etree
import re
import requests
from requests.auth import HTTPBasicAuth
import json

# eulfedora
import eulfedora

# rdflib
from rdflib.compare import to_isomorphic, graph_diff

# fuzzy matching lib
from fuzzywuzzy import fuzz

import localConfig

editRELS = Blueprint('editRELS', __name__, template_folder='templates', static_folder="static")


@editRELS.route('/editRELS', methods=['POST', 'GET'])
@utilities.objects_needed
@login_required
@roles.auth(['admin'])
def index():	
	return render_template("editRELS_index.html")


@editRELS.route('/editRELS/add', methods=['POST', 'GET'])
@utilities.objects_needed
@login_required
@roles.auth(['admin'])
def editRELS_add():	
	
	# instantiate forms
	form = RDF_edit()

	return render_template("editRELS_add.html",form=form)


@editRELS.route('/editRELS/advanced', methods=['POST', 'GET'])
@utilities.objects_needed
@login_required
@roles.auth(['admin'])
def editRELS_advanced():

	'''
	/tasks/editRELS/blanket?PIDnum={{(PIDnum - 1)}}
	'''

	# get PID to examine, if noted
	if request.args.get("PIDnum") != None:
		PIDnum = int(request.args.get("PIDnum"))		
	else:
		PIDnum = 0

	# gen PIDlet
	PIDlet = jobs.genPIDlet(int(PIDnum))
	if PIDlet == False:
		return utilities.applicationError("PIDnum is out of range.")
	PIDlet['pURL'] = "/tasks/editRELS/advanced?PIDnum="+str(int(PIDnum)-1)
	PIDlet['nURL'] = "/tasks/editRELS/advanced?PIDnum="+str(int(PIDnum)+1)	

	# instantiate forms
	form = RDF_edit()		

	# get triples for 1st object
	riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+PIDlet['cPID'], predicate=None, object=None)
	
	# filter out RELS-EXT and WSUDOR predicates
	riquery_filtered = []
	for s,p,o in riquery:
		try:
			if "relations-external" in p or "WSUDOR-Fedora-Relations" in p:
				riquery_filtered.append((p,o))	
		except:
			logging.debug("Could not parse RDF relationship")
	riquery_filtered.sort() #mild sorting applied to group WSUDOR or RELS-EXT		

	# Raw Datastream via Fedora API
	###############################################################	
	raw_xml_URL = "http://%s/fedora/objects/%s/datastreams/RELS-EXT/content" % (localConfig.FEDORA_HOST, PIDlet['cPID'])
	raw_xml = requests.get(raw_xml_URL).text.encode("utf-8")
	###############################################################
	
	# return render_template("editRELS_advanced.html",riquery_filtered=riquery_filtered,PID=PIDs[PIDnum],PIDnum=PIDnum,len_PIDs=len(PIDs),form=form,raw_xml=raw_xml)
	return render_template("editRELS_advanced.html",riquery_filtered=riquery_filtered,PIDlet=PIDlet,form=form,raw_xml=raw_xml)


@editRELS.route('/editRELS/shared', methods=['POST', 'GET'])
@utilities.objects_needed
@roles.auth(['admin'])
def editRELS_shared():
	'''
	Will return only RDF statements shared (predicate AND object) by all PIDs	

	- Requires workaround for large queries...
		- Eulfedora (uses GET, too small)
		- POST requests 100+ break sparql
		- Solution: for scenarios with 100+ PIDs, break into smaller queries, then mix together in results

	'''
	# get PIDs	
	PIDs = jobs.getSelPIDs()

	# shared relationships	
	shared_relationships = []

	# shared function for whole or chunked query
	def risearchQuery(list_of_PIDs):
		# construct where statement for query
		where_statement = ""
		for PID in list_of_PIDs:
			if PID != None:				
				where_statement += "<fedora:%s> $predicate $object . " % (PID)
		query_statement = "select $predicate $object from <#ri> where {{ %s }}" % (where_statement)		

		# logging.debug(query_statement)
		
		base_URL = "http://%s:%s@%s/fedora/risearch" % (FEDORA_USER, FEDORA_PASSWORD, localConfig.FEDORA_HOST)
		payload = {
			"lang" : "sparql",
			"query" : query_statement,
			"flush" : "false",
			"type" : "tuples",
			"format" : "JSON"
		}
		r = requests.post(base_URL, auth=HTTPBasicAuth(FEDORA_USER, FEDORA_PASSWORD), data=payload )
		risearch = json.loads(r.text)
		return risearch

	# if more than 100 PIDs, chunk into sub-queries
	if len(PIDs) > 100:		

		def grouper(iterable, chunksize, fillvalue=None):
			from itertools import izip_longest
			args = [iter(iterable)] * chunksize
			return izip_longest(*args, fillvalue=fillvalue)

		chunks =  grouper(PIDs,100)

		for chunk in chunks:			

			# perform query
			risearch = risearchQuery(chunk)

			chunk_list = []			
			for each in risearch['results']:
				tup = (each['predicate'],each['object'])				
				chunk_list.append(tup)
			try:
				curr_set = set.intersection(curr_set,set(chunk_list))
			except:
				curr_set = set(chunk_list)

		logging.debug(curr_set)
		shared_relationships = curr_set
		

	else:
		# perform query
		risearch = risearchQuery(PIDs)
		shared_relationships = [ (each['predicate'], each['object']) for each in risearch['results'] ]


	return render_template('editRELS_shared.html',shared_relationships=shared_relationships)


@editRELS.route('/editRELS/regexConfirm', methods=['POST', 'GET'])
@login_required
@roles.auth(['admin'])
def regexConfirm():
		
	# get PIDs	
	PIDs = jobs.getSelPIDs()			
	form_data = request.form	

	# search / replace
	orig_string = request.form['raw_xml']
	regex_search = request.form['regex_search'].encode('utf-8')
	regex_replace = request.form['regex_replace'].encode('utf-8')
	new_string = re.sub(regex_search,regex_replace,orig_string)	
		
	#debug
	return_package = {
		"orig_string":orig_string,
		"new_string":new_string,
		"regex_search":regex_search,
		"regex_replace":regex_replace		
	}	

	# check diff - if ratio == 100, XML is identical, simply reordered by RDF query
	if orig_string == new_string:
		return_package['string_match'] = True	
	
	return render_template("editRELS_regexConfirm.html",return_package=return_package)

@roles.auth(['admin'], is_celery=True)
def editRELS_add_worker(job_package):
	PID = job_package['PID']		
	obj_ohandle = fedora_handle.get_object(PID)	

	form_data = job_package['form_data']	

	if "literal" in form_data:
		predicate_string = form_data['predicate_literal'].encode('utf-8').strip()	
	else:
		predicate_string = form_data['predicate'].encode('utf-8').strip()

	object_string = form_data['obj'].encode('utf-8').strip()
	return obj_ohandle.add_relationship(predicate_string, object_string)


@roles.auth(['admin'], is_celery=True)
def editRELS_purge_worker(job_package):

	PID = job_package['PID']		
	obj_ohandle = fedora_handle.get_object(PID)	

	form_data = job_package['form_data']
	predicate_string = form_data['predicate'].encode('utf-8').strip()
	object_string = form_data['object'].encode('utf-8').strip()

	logging.debug("Removing the following predicate / subject: %s /%s" % (predicate_string, object_string))
		
	return obj_ohandle.purge_relationship(predicate_string, object_string)


@roles.auth(['admin'], is_celery=True)
def editRELS_modify_worker(job_package):

	PID = job_package['PID']		
	obj_ohandle = fedora_handle.get_object(PID)	

	form_data = job_package['form_data']

	new_predicate_string = form_data['new_predicate'].encode('utf-8').strip()
	old_predicate_string = form_data['old_predicate'].encode('utf-8').strip()
	new_object_string = form_data['new_object'].encode('utf-8').strip()	
	old_object_string = form_data['old_object'].encode('utf-8').strip()
		
	return obj_ohandle.modify_relationship(old_predicate_string, old_object_string, new_object_string)


@roles.auth(['admin'], is_celery=True)
def editRELS_edit_worker(job_package):		
	'''
	Takes modified raw RDF XML, applies to all PIDs in job.	
	'''	

	PID = job_package['PID']		
	obj_ohandle = fedora_handle.get_object(PID)

	# Eulfedora
	###############################################################
	# obj_ohandle = fedora_handle.get_object(PIDs[PIDnum])	
	# try:
	# 	raw_xml = obj_ohandle.rels_ext.content.serialize()
	# except:
	# 	raw_xml = "COULD NOT PARSE"
	###############################################################

	# Raw Datastream via Fedora API
	###############################################################	
	raw_xml_URL = "http://%s/fedora/objects/%s/datastreams/RELS-EXT/content" % (localConfig.FEDORA_HOST, PID)
	pre_mod_xml = requests.get(raw_xml_URL).text.encode("utf-8")
	###############################################################

	# get modified XML
	form_data = job_package['form_data']
	raw_xml = form_data['raw_xml']

	# check diff - if ratio == 100, XML is identical, simply reordered by RDF query
	diff_ratio = fuzz.token_set_ratio(raw_xml,pre_mod_xml)	
	logging.debug("difference ratio: %s" % diff_ratio)
	if diff_ratio == 100:
		return "RDF XML un-modified, skipping DB insert and Fedora updating."

	# else, continue
	else:

		# if first PID in job, save pre-modified XML in job_rollback table
		if job_package['step'] == 1:
			db.session.add(models.job_rollback(job_package["job_num"],job_package["username"], "editRELS_edit_worker", pre_mod_xml ))	
			db.session.commit()

		# parse xml, change PID for "about" attribute
		encoded_xml = raw_xml.encode('utf-8')
		parser = etree.XMLParser(ns_clean=True, recover=True, encoding='utf-8')
		XMLroot = etree.fromstring(encoded_xml, parser=parser)
		desc_tag = XMLroot.xpath("//rdf:Description", namespaces=XMLroot.nsmap)
		for desc_tag in XMLroot.xpath("//rdf:Description",namespaces=XMLroot.nsmap):
			desc_tag.attrib['{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about'] = "info:fedora/%s" % (PID)
		new_raw = etree.tostring(XMLroot)
		
		# similar to addDS functionality
		# initialized DS object
		newDS = eulfedora.models.DatastreamObject(obj_ohandle, "RELS-EXT", "RELS-EXT", control_group="X")	

		# construct DS object	
		newDS.mimetype = "application/rdf+xml"
		# content		
		newDS.content = new_raw	

		# save constructed object
		logging.debug(newDS.save())


@roles.auth(['admin'], is_celery=True)
def editRELS_regex_worker(job_package):		
	
	PID = job_package['PID']		
	obj_ohandle = fedora_handle.get_object(PID)	
	
	# Eulfedora
	###############################################################
	# obj_ohandle = fedora_handle.get_object(PIDs[PIDnum])	
	# try:
	# 	raw_xml = obj_ohandle.rels_ext.content.serialize()
	# except:
	# 	raw_xml = "COULD NOT PARSE"
	###############################################################

	# Raw Datastream via Fedora API
	###############################################################	
	raw_xml_URL = "http://%s/fedora/objects/%s/datastreams/RELS-EXT/content" % (localConfig.FEDORA_HOST, PID)
	raw_xml = requests.get(raw_xml_URL).text.encode("utf-8")
	###############################################################
	
	# get regex parameters
	form_data = job_package['form_data']	

	# search / replace	
	regex_search = form_data['regex_search'].encode('utf-8')
	regex_replace = form_data['regex_replace'].encode('utf-8')
	new_string = re.sub(regex_search,regex_replace,raw_xml)		

	# similar to addDS functionality	
	newDS = eulfedora.models.DatastreamObject(obj_ohandle, "RELS-EXT", "RELS-EXT", control_group="X")	

	# construct DS object	
	newDS.mimetype = "application/rdf+xml"
	# content		
	newDS.content = new_string	

	# save constructed object
	logging.debug(newDS.save())
























