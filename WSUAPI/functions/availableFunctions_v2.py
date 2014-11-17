# Python imports
import requests
import ast
import urllib
from paste.util.multidict import MultiDict
import json
import re
import hashlib
import xmltodict
import subprocess
import ldap
import mimetypes

# Fedora and Risearch imports
from fedDataSpy import checkSymlink

# Solr imports
import sunburnt

# utilities
from utils import *

# config
from localConfig import *

# modules from WSUDOR_Manager
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager.solrHandles import solr_handle

from availableFunctions import *


# next gen singleObject function
def singleObjectPackage(getParams):
	
	# get PID
	PID = getParams['PID'][0]
	PID_suffix = PID.split(":")[1]

	'''
	each sub-component returns a tuple with desired name and results as dictionary
	'''

	# determine if object exists and is active
	isActive_dict = json.loads(getObjectXML(getParams))
	if isActive_dict['object_status'] == "Absent" or isActive_dict['object_status'] == "Inactive":
		# not present, return reduced dictionary
		return_dict = {		
			'isActive':isActive_dict
		}
		return json.dumps(return_dict)	


	def hasPartOf_func():
		# runs hasPartOf(), gets components and their representations ()
		# saves to 'hasPartOf'	
		return json.loads(hasPartOf(getParams))

	def main_imageDict_func():
		# create small dictinoary with image datastreams for main intellectual object
		# saves to 'main_imageDict'
		query = {
			"q" : "id:*{PID_suffix}".format(PID_suffix=PID_suffix),
			"rows" : 1,
			"start" : 0		
		}
		# perform query
		doc_handle = solr_handle.search(**query).documents[0]
		main_imageDict = {
			"thumbnail" : doc_handle['rels_isRepresentedBy'][0]+"_THUMBNAIL",
			"preview" : doc_handle['rels_isRepresentedBy'][0]+"_PREVIEW",
			"access" : doc_handle['rels_isRepresentedBy'][0],
			"jp2" : doc_handle['rels_isRepresentedBy'][0]+"_JP2"
		}
		return main_imageDict

	def parts_imageDict_func():
		# returns image dictionary for parts, reusing hasPartOf_results
		# saves to 'parts_imageDict'	
		handle = json.loads(hasPartOf(getParams))	
		print "HANDLE HERE:",handle
		parts_imageDict = {}
		parts_imageDict['parts_list'] = []
		for each in handle['results']:
			parts_imageDict['parts_list'].append(each['ds_id'])
			parts_imageDict[each['ds_id']] = {
				'ds_id':each['ds_id'],
				'pid':each['pid'],
				'thumbnail' : fedora_handle.risearch.get_subjects("info:fedora/fedora-system:def/relations-internal#isThumbnailOf", "{object}".format(object=each['object'])).next().split("/")[-1],
				'preview' : fedora_handle.risearch.get_subjects("info:fedora/fedora-system:def/relations-internal#isPreviewOf", "{object}".format(object=each['object'])).next().split("/")[-1],
				'jp2' : fedora_handle.risearch.get_subjects("info:fedora/fedora-system:def/relations-internal#isJP2Of", "{object}".format(object=each['object'])).next().split("/")[-1]
			}
		print "PARTS DICT",parts_imageDict
		return parts_imageDict

	def objectSolrDoc_func():
		# return entire solr doc for object, straight through
		# saves to 'objectSolrDoc'
		query = {
			"q" : "id:*{PID_suffix}".format(PID_suffix=PID_suffix),
			"rows" : 1,
			"start" : 0		
		}
		# perform query
		objectSolrDoc = solr_handle.search(**query).documents[0]
		return objectSolrDoc


	def isMemberOfCollection_func():
		# returns collections the object is a part of
		# saves to 'isMemberOfCollection'
		return json.loads(isMemberOfCollection(getParams))


	def hasMemberOf_func():
		# returns collections the object is a part of
		# saves to 'hasMemberOf'
		return json.loads(hasMemberOf(getParams))
		
	# run all functions and return
	return_dict = {
		'hasPartOf':hasPartOf_func(),
		'main_imageDict':main_imageDict_func(),		
		'parts_imageDict':parts_imageDict_func(),
		'objectSolrDoc':objectSolrDoc_func(),
		'isMemberOfCollection':isMemberOfCollection_func(),
		'hasMemberOf':hasMemberOf_func(),
		'isActive':isActive_dict
	}

	return json.dumps(return_dict)








