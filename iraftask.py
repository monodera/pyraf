"""module iraftask.py -- defines IrafTask and IrafPkg classes

$Id$

R. White, 1999 December 15
"""

import os, sys, string, types, copy, re
import minmatch, subproc
import iraf, irafpar, irafexecute, epar, cl2py


# -----------------------------------------------------
# IRAF task class
# -----------------------------------------------------

class IrafTask:

	"""IRAF task class"""

	def __init__(self, prefix, name, suffix, filename, pkgname, pkgbinary):
		sname = string.replace(name, '.', '_')
		if sname != name:
			print "Warning: '.' illegal in task name, changing", name, \
				"to", sname
		spkgname = string.replace(pkgname, '.', '_')
		if spkgname != pkgname:
			print "Warning: '.' illegal in pkgname, changing", pkgname, \
				"to", spkgname
		self._name = sname
		self._pkgname = spkgname
		self._pkgbinary = []
		self.addPkgbinary(pkgbinary)
		# tasks with names starting with '_' are implicitly hidden
		if name[0:1] == '_':
			self._hidden = 1
		else:
			self._hidden = 0
		if prefix == '$':
			self._hasparfile = 0
		else:
			self._hasparfile = 1
		if suffix == '.tb':
			self._tbflag = 1
		else:
			self._tbflag = 0
		# full path names and parameter list get filled in on demand
		self._fullpath = None
		# parameters have a current set of values and a default set
		self._currentParList = None
		self._defaultParList = None
		# parameter file has a current value and a default value
		self._currentParpath = None
		self._defaultParpath = None
		self._scrunchParpath = None
		self._parDictList = None
		if filename and filename[0] == '$':
			# this is a foreign task
			self._foreign = 1
			self._filename = filename[1:]
			# handle weird syntax for names
			if self._filename == 'foreign':
				self._filename = name
			elif self._filename[:8] == 'foreign ':
				self._filename = name + self._filename[7:]
			elif filename[:2] == '$0':
				self._filename = name + filename[2:]
		else:
			self._foreign = 0
			self._filename = filename

	# parameters are accessible as attributes

	def __getattr__(self,name):
		if name[:1] == '_': raise AttributeError(name)
		self.initTask()
		try:
			return self.getParam(name,native=1)
		except SyntaxError, e:
			raise AttributeError(str(e))

	def __setattr__(self,name,value):
		# hidden Python parameters go into the standard dictionary
		# (hope there are none of these in IRAF tasks)
		if name[:1] == '_':
			self.__dict__[name] = value
		else:
			self.initTask()
			self.setParam(name,value)

	# public accessor functions for attributes

	def getName(self):      return self._name
	def getPkgname(self):   return self._pkgname
	def getPkgbinary(self): return self._pkgbinary
	def isHidden(self):     return self._hidden
	def hasParfile(self):   return self._hasparfile
	def getTbflag(self):    return self._tbflag
	def getForeign(self):   return self._foreign
	def getFilename(self):  return self._filename

	def getFullpath(self):
		"""Return full path name of executable"""
		self.initTask()
		return self._fullpath

	def getParpath(self):
		"""Return full path name of parameter file"""
		self.initTask()
		return self._currentParpath

	def getParList(self):
		"""Return list of all parameter objects"""
		self.initTask()
		return self._currentParList.getParList()

	def getParDict(self):
		"""Return (min-match) dictionary of all parameter objects"""
		self.initTask()
		return self._currentParList.getParDict()

	def addPkgbinary(self, pkgbinary):
		"""Add another entry in list of possible package binary locations

		Parameter can be a string or a list of strings"""

		if not pkgbinary:
			return
		elif type(pkgbinary) == types.StringType:
			if pkgbinary and (pkgbinary not in self._pkgbinary):
				self._pkgbinary.append(pkgbinary)
		else:
			for pbin in pkgbinary:
				if pbin and (pbin not in self._pkgbinary):
					self._pkgbinary.append(pbin)

	# public access to set hidden attribute, which can be specified
	# in a separate 'hide' statement

	def setHidden(self,value=1):     self._hidden = value

	def getParObject(self,param):
		"""Get the IrafPar object for a parameter"""
		self.initTask()
		return self._currentParList.getParObject(param)

	# allow running task using taskname() or with
	# parameters as arguments, including keyword=value form.

	def __call__(self,*args,**kw):
		apply(self.run,args,kw)

	def run(self,*args,**kw):
		"""Execute this task with the specified arguments"""
		self.initTask()
		if self._foreign:
			print "No run yet for foreign task '" + self._name + "'"
		else:
			# special _nosave keyword turns off saving of parameters
			if kw.has_key('_nosave'):
				nosave = kw['_nosave']
				del kw['_nosave']
			else:
				nosave = 0
			# Special Stdout, Stdin, Stderr keywords are used to redirect IO
			redirKW, closeFHList = iraf.redirProcess(kw)
			# set parameters
			newParList = apply(self.setParList,args,kw)
			if iraf.Verbose>1:
				print "Connected subproc run ", self._name, \
					"("+self._fullpath+")"
				newParList.lpar()
			try:
				# create the list of parameter dictionaries to use
				self.setParDictList()
				# run the task using new par list
				oldValue = self._parDictList[0]
				self._parDictList[0] = (self._name,newParList.getParDict())
				try:
					apply(irafexecute.IrafExecute,
						(self, iraf.varDict), redirKW)
					changed = self.updateParList(newParList)
					if changed and (nosave==0):
						rv = self.save()
						if iraf.Verbose>1: print rv
					if iraf.Verbose>1: print 'Successful task termination'
				finally:
					iraf.redirReset([], closeFHList)
					self._parDictList[0] = oldValue
			except irafexecute.IrafProcessError, value:
				raise iraf.IrafError("Error running IRAF task " + self._name +
					"\n" + str(value))

	def getMode(self, parList=None):
		"""Returns mode string for this task

		Searches up the task, package, cl hierarchy for automatic modes
		"""
		if parList is not None:
			mode = parList.get('mode',prompt=0)
		else:
			# get parameter from first element of parDictList in case
			# we are currently running the task
			if self._parDictList is None: self.setParDictList()
			name, pdict = self._parDictList[0]
			mode = pdict['mode'].get(prompt=0)
		if mode[:1] != "a": return mode

		# cl is the court of last resort, don't look at its packages
		if self == iraf.cl: return "h"

		# package name is undefined only at very start of initialization
		# just use the standard default
		if not self._pkgname: return "ql"

		# up we go -- look in parent package
		pkg = iraf.getPkg(self._pkgname)
		# clpackage is at top and is its own parent
		if pkg != self:
			return pkg.getMode()
		# didn't find it in the package hierarchy, so use cl mode
		mode = iraf.cl.mode
		# default is hidden if automatic all the way to top
		if mode[:1] == "a":
			return "h"
		else:
			return mode

	def setParList(self,*args,**kw):
		"""Set arguments to task

		Creates a copy of the task parameter list and returns the
		copy with parameters set.  It is up to subsequent code (in
		the run method) to propagate these changes to the persistent
		parameter list.
		"""
		self.initTask()
		newParList = copy.deepcopy(self._currentParList)
		apply(newParList.setParList, args, kw)
		# set mode of automatic parameters
		mode = self.getMode(newParList)
		for p in newParList.getParList():
			p.mode = string.replace(p.mode,"a",mode)
		return newParList

	def updateParList(self, newParList):
		"""Update parameter list after successful task completion

		Returns true if any parameters change
		"""
		mode = self.getMode(newParList)
		changed = 0
		for par in newParList.getParList():
			if par.name != "$nargs" and \
			 (par.isChanged() or (par.isCmdline() and par.isLearned(mode))):
				changed = 1
				# get task parameter object
				tpar = self._currentParList.getParObject(par.name)
				# set its value -- don't bother with type checks since
				# the new and old parameters must be identical
				tpar.value = par.value
				# propagate other mutable fields too
				# (note IRAF does not propagate prompt, which I consider a bug)
				tpar.min = par.min
				tpar.max = par.max
				tpar.choice = par.choice
				# don't propagate modes since I changed them
				# tpar.mode = par.mode
				tpar.prompt = par.prompt
				tpar.setChanged()
		return changed

	def setParDictList(self):
		"""Set the list of parameter dictionaries for task execution.

		Parameter dictionaries for execution consist of this
		task's parameters (which includes any psets
		referenced), all the parameters for packages that have
		been loaded, and the cl parameters.  Each dictionary
		has an associated name (because parameters could be
		asked for as task.parname as well as just parname).

		Create this list anew for each execution in case the
		list of loaded packages has changed.  It is stored as
		an attribute of this object so it can be accessed by
		the getParam() and setParam() methods.
		"""

		self.initTask()
		if self._currentParList:
			parDictList = [(self._name,self._currentParList.getParDict())]
		else:
			parDictList = [(self._name,{})]
		# package parameters
		# only include each pkg once
		pinc = {}
		for i in xrange(len(iraf.loadedPath)):
			pkg = iraf.loadedPath[-1-i]
			pkgname = pkg.getName()
			if not pinc.has_key(pkgname):
				pd = pkg.getParDict()
				# don't include null dictionaries
				if pd:
					parDictList.append( (pkg.getName(), pd) )
		# cl parameters
		cl = iraf.cl
		if cl is not None:
			parDictList.append( (iraf.cl.getName(),iraf.cl.getParDict()) )
		self._parDictList = parDictList

	def setParam(self,qualifiedName,newvalue,check=1):
		"""Set parameter specified by qualifiedName to newvalue.

		qualifiedName can be a simple parameter name or can be
		[[package.]task.]paramname[.field].
		If check is set to zero, does not check value to make sure it
		satisfies min-max range or choice list.
		"""

		if self._parDictList is None: self.setParDictList()

		package, task, paramname, pindex, field = _splitName(qualifiedName)

		# special syntax for package parameters
		if task == "_": task = self._pkgname

		if task or package:
			if not package:
				# maybe this task is the name of one of the dictionaries?
				for dictname, paramdict in self._parDictList:
					if dictname == task:
						if paramdict.has_key(paramname):
							paramdict[paramname].set(newvalue,index=pindex,
								field=field,check=check)
							return
						else:
							raise iraf.IrafError("Attempt to set unknown parameter " +
								qualifiedName)
			# Not one of our dictionaries, so must find the relevant task
			if package: task = package + '.' + task
			try:
				tobj = iraf.getTask(task)
				# reattach the index and/or field
				if pindex: paramname = paramname + '[' + `pindex+1` + ']'
				if field: paramname = paramname + '.' + field
				tobj.setParam(paramname,newvalue,check=check)
				return
			except KeyError:
				raise iraf.IrafError("Could not find task " + task +
					" to get parameter " + qualifiedName)
			except iraf.IrafError, e:
				raise iraf.IrafError(e + "\nFailed to set parameter " +
					qualifiedName)

		# no task specified, just search the standard dictionaries
		for dictname, paramdict in self._parDictList:
			if paramdict.has_key(paramname):
				paramdict[paramname].set(newvalue,index=pindex,
					field=field,check=check)
				return
		else:
			raise iraf.IrafError("Attempt to set unknown parameter " +
				qualifiedName)

	def getParam(self,qualifiedName,native=0,mode=None):
		"""Return parameter specified by qualifiedName.

		qualifiedName can be a simple parameter name or can be
		[[package.]task.]paramname[.field].
		Paramname can also have an optional subscript, "param[1]".
		If native is non-zero, returns native format (e.g. float for
		floating point parameter.)  Default is return string value.
		"""

		if self._parDictList is None: self.setParDictList()
		package, task, paramname, pindex, field = _splitName(qualifiedName)

		# special syntax for package parameters
		if task == "_": task = self._pkgname

		# get mode (used for prompting behavior)
		if mode is None: mode = self.getMode()

		if task and (not package):
			# maybe this task is the name of one of the dictionaries?
			for dictname, paramdict in self._parDictList:
				if dictname == task:
					if paramdict.has_key(paramname):
						v = paramdict[paramname].get(index=pindex,field=field,
								native=native,mode=mode)
						if type(v) is types.StringType and v[:1] == ")":
							# parameter indirection: call getParam recursively
							# I'm making the assumption that indirection in a
							# field (e.g. in the min or max value) is allowed
							# and that it uses exactly the same syntax as
							# the argument to getParam, i.e. ')task.param'
							# refers to the p_value of the parameter,
							# ')task.param.p_min' refers to the min or
							# choice string, etc.
							return self.getParam(v[1:],native=native,
									mode=mode)
						else:
							return v
					else:
						raise iraf.IrafError("Unknown parameter requested: " +
							qualifiedName)

		if package or task:
			# Not one of our dictionaries, so must find the relevant task
			if package: task = package + '.' + task
			try:
				tobj = iraf.getTask(task)
				if field:
					return tobj.getParam(paramname+'.'+field,native=native,
							mode=mode)
				else:
					return tobj.getParam(paramname,native=native,mode=mode)
			except KeyError:
				raise iraf.IrafError("Could not find task " + task +
					" to get parameter " + qualifiedName)
			except iraf.IrafError, e:
				raise iraf.IrafError(e + "\nFailed to get parameter " +
					qualifiedName)

		for dictname, paramdict in self._parDictList:
			if paramdict.has_key(paramname):
				v = paramdict[paramname].get(index=pindex,field=field,
						native=native,mode=mode)
				if type(v) is types.StringType and v[:1] == ")":
					# parameter indirection: call getParam recursively
					return self.getParam(v[1:],native=native,mode=mode)
				else:
					return v
		else:
			raise iraf.IrafError("Unknown parameter requested: " +
				qualifiedName)

	def lpar(self,verbose=0):
		"""List the task parameters"""
		self.initTask()
		if not self._hasparfile:
			sys.stderr.write("Task %s has no parameter file\n" % self._name)
			sys.stderr.flush()
		else:
			self._currentParList.lpar(verbose=verbose)

	def epar(self):
		"""Edit the task parameters"""
		self.initTask()
		if not self._hasparfile:
			sys.stderr.write("Task %s has no parameter file\n" % self._name)
			sys.stderr.flush()
		else:
			epar.epar(self)

	def dpar(self):
		"""Dump the task parameters"""
		self.initTask()
		if not self._hasparfile:
			sys.stderr.write("Task %s has no parameter file\n" % self._name)
			sys.stderr.flush()
		else:
			self._currentParList.dpar(self._name)

	def save(self,filename=None):
		"""Write task parameters in .par format to filename (name or handle)

		If filename is omitted, writes to uparm scrunch file (if possible)
		Returns a string with the results.
		"""
		self.initTask()
		if not self._hasparfile: return
		if filename is None:
			if self._scrunchParpath:
				filename = self._scrunchParpath
			else:
				status = "Unable to save parameters for task %s" % \
					(self._name,)
				if iraf.Verbose>0: print status
				return status
		rv = self._currentParList.save(filename)
		if type(filename) is types.StringType:
			self._currentParpath = filename
		elif hasattr(filename,'name'):
			self._currentParpath = filename.name
		return rv

	def initTask(self):
		"""Fill in full pathnames of files and read parameter file(s)"""
		if self._filename and not self._fullpath: self.initFullpath()
		if self._currentParList is None:
			self.initParpath()
			self.initParList()

	def initFullpath(self):
		"""Fill in full pathname of executable"""

		# This follows the search strategy used by findexe in
		# cl/exec.c: first it checks in the BIN directory for the
		# "installed" version of the executable, and if that is not
		# found it tries the pathname given in the TASK declaration.

		# Expand iraf variables.  We will try both paths if the expand fails.
		try:
			exename1 = iraf.Expand(self._filename)
			# get name of executable file without path
			basedir, basename = os.path.split(exename1)
		except iraf.IrafError, e:
			if iraf.Verbose>0:
				print "Error searching for executable for task " + \
					self._name
				print str(e)
			exename1 = ""
			# make our best guess that the basename is what follows the
			# last '$' in _filename
			basedir = ""
			s = string.split(self._filename, "$")
			basename = s[-1]
		if basename == "":
			self._fullpath = ""
			raise iraf.IrafError("No filename in task %s definition: `%s'"
				% (self._name, self._filename))
		# for foreign tasks, just set path to filename (XXX will
		# want to improve this by checking os path for existence)
		if self._foreign:
			self._fullpath = self._filename
		else:
			# first look in the task binary directories
			exelist = []
			for pbin in self._pkgbinary:
				try:
					exelist.append(iraf.Expand(pbin + basename))
				except iraf.IrafError, e:
					if iraf.Verbose>0:
						print "Error searching for executable for task " + \
							self._name
						print str(e)
			for exename2 in exelist:
				if os.path.exists(exename2):
					self._fullpath = exename2
					break
			else:
				if os.path.exists(exename1):
					self._fullpath = exename1
				else:
					self._fullpath = ""
					raise iraf.IrafError("Cannot find executable for task " +
						self._name + "\nTried "+exename1+" and "+exename2)

	def initParpath(self):
		"""Initialize parameter file paths"""

		if not self._filename:
			# if filename is missing we won't be able to find parameter file
			# set hasparfile flag to zero if that is OK
			self.noParFile()
			self._hasparfile = 0

		if not self._hasparfile:
			# no parameter file
			self._defaultParpath = ""
			self._currentParpath = ""
			self._scrunchParpath = ""
			return

		try:
			exename1 = iraf.Expand(self._filename)
			basedir, basename = os.path.split(exename1)
		except iraf.IrafError, e:
			if iraf.Verbose>0:
				print "Error expanding executable name for task " + \
					self._name
				print str(e)
			exename1 = ""
			basedir = ""

		# default parameters are found with task
		self._defaultParpath = os.path.join(basedir,self._name + ".par")
		if not os.path.exists(self._defaultParpath):
			self.noParFile()
			self._defaultParpath = ""

		# uparm has scrunched version of par filename with saved parameters
		if iraf.varDict.has_key("uparm"):
			self._scrunchParpath = iraf.Expand("uparm$" +
						self.scrunchName() + ".par")
		else:
			self._scrunchParpath = None

	def noParFile(self):
		"""Decide what to do if .par file is not found"""
		# Here I raise an exception, but subclasses (e.g., CL tasks)
		# can do something different.
		raise iraf.IrafError("Cannot find .par file for task " + self._name)

	def initParList(self):

		"""Initialize parameter list by reading parameter file"""

		if not self._hasparfile: return

		self._defaultParList = irafpar.IrafParList(self._name,
							self._defaultParpath)

		if self._scrunchParpath and os.path.exists(self._scrunchParpath):
			self._currentParpath = self._scrunchParpath
			self._currentParList = irafpar.IrafParList(self._name,
								self._currentParpath)
			# are lists consistent?
			if not self.isConsistentPar():
				sys.stderr.write("uparm parameter list `%s' inconsistent "
				  "with default parameters for %s `%s'\n" %
				  (self._currentParpath, self.__class__.__name__, self._name,))
				sys.stderr.flush()
				print 'default'
				self._defaultParList.lpar(verbose=1)
				print 'current'
				self._currentParList.lpar(verbose=1)
				#XXX just toss it for now -- later can try to merge new,old
				self._currentParpath = self._defaultParpath
				self._currentParList = copy.deepcopy(self._defaultParList)
		else:
			self._currentParpath = self._defaultParpath
			self._currentParList = copy.deepcopy(self._defaultParList)

	def isConsistentPar(self):
		"""Check current par list and default par list for consistency"""
		return self._currentParList.isConsistent(self._defaultParList)

	def unlearn(self):
		"""Reset task parameters to their default values"""
		self.initTask()
		if self._hasparfile:
			if self._defaultParList:
				self._currentParpath = self._defaultParpath
				self._currentParList = copy.deepcopy(self._defaultParList)
			else:
				raise iraf.IrafError("Cannot find default .par file for task " +
					self._name)

	def scrunchName(self):
		"""Return scrunched version of filename (used for uparm files)

		Scrunched version of filename is chars 1,2,last from package
		name and chars 1-5,last from task name.
		"""
		s = self._pkgname[0:2]
		if len(self._pkgname) > 2:
			s = s + self._pkgname[-1:]
		s = s + self._name[0:5]
		if len(self._name) > 5:
			s = s + self._name[-1:]
		return s

	def __repr__(self):
		return '<%s %s at %s>' % (self.__class__.__name__, self._name,
							hex(id(self))[2:])

	def __str__(self):
		s = '<%s %s (%s) Pkg: %s Bin: %s' % \
			(self.__class__.__name__, self._name, self._filename, 
			self._pkgname, self._pkgbinary[0])
		for pbin in self._pkgbinary[1:]: s = s + ':' + pbin
		if self._foreign: s = s + ' Foreign'
		if self._hidden: s = s + ' Hidden'
		if self._hasparfile == 0: s = s + ' No parfile'
		if self._tbflag: s = s + ' .tb'
		return s + '>'

# -----------------------------------------------------
# IRAF Pset class
# -----------------------------------------------------

class IrafPset(IrafTask):

	"""IRAF pset class (special case of IRAF task)"""

	def __init__(self, prefix, name, suffix, filename, pkgname, pkgbinary):
		IrafTask.__init__(self,prefix,name,suffix,filename,pkgname,pkgbinary)
		# check that parameters are consistent with pset:
		# - not a foreign task
		# - has a parameter file
		if self.getForeign():
			raise iraf.IrafError("Bad filename for pset %s: %s" %
				(self.getName(), filename))
		if not self.hasParfile():
			raise KeyError("Pset "+self.getName()+" has no parameter file")

	def run(self,*args,**kw):
		# should executing a pset run epar?
		raise iraf.IrafError("Cannot execute Pset " + self.getName())

# -----------------------------------------------------
# parDictList search class (helper for IrafCLTask)
# -----------------------------------------------------

class ParDictListSearch:
	def __init__(self, taskObj):
		self.__dict__['_taskObj'] = taskObj
	def __getattr__(self, paramname):
		if paramname[:1] == '_': raise AttributeError(paramname)
		try:
			return self._taskObj.getParam(paramname,native=1)
		except SyntaxError, e:
			raise AttributeError(str(e))
	def __setattr__(self, paramname, value):
		if paramname[:1] == '_': raise AttributeError(paramname)
		self._taskObj.setParam(paramname, value)

# -----------------------------------------------------
# IRAF CL task class
# -----------------------------------------------------

class IrafCLTask(IrafTask):

	"""IRAF CL task class"""

	def __init__(self, prefix, name, suffix, filename, pkgname, pkgbinary):
		# allow filename to be a filehandle or a filename
		if type(filename) == types.StringType:
			fh = None
		else:
			if not hasattr(filename,'read'):
				raise TypeError(
					'filename must be either a string or a filehandle')
			fh = filename
			if hasattr(fh,'name'):
				filename = fh.name
			else:
				filename = None
		IrafTask.__init__(self,prefix,name,suffix,filename,pkgname,pkgbinary)
		if self.getForeign():
			raise iraf.IrafError("CL task cannot be foreign " +
				self.getName() + ": " + filename)
		# placeholder for Python translation of CL code
		# (lazy instantiation)
		self._pycode = None
		if fh is not None:
			# if filehandle was specified, go ahead and do the
			# initialization now
			self.initTask(filehandle=fh)

	def noParFile(self):
		"""Decide what to do if .par file is not found"""
		# For CL tasks, it is OK if no .par
		pass

	def isConsistentPar(self):
		"""Check current par list and default par list for consistency"""
		# they do not have to be consistent for CL task (at least not
		# where this is called, in IrafTask.initTask).
		#XXX This is a bit lax, eh?  Need something a bit stricter.
		return 1

	def run(self,*args,**kw):
		"""Execute this task with the specified arguments"""
		self.initTask()
		if kw.has_key('_nosave'):
			nosave = kw['_nosave']
			del kw['_nosave']
		else:
			nosave = 0
		# Special Stdout, Stdin, Stderr keywords are used to redirect IO
		redirKW, closeFHList = iraf.redirProcess(kw)
		# set parameters
		newParList = apply(self.setParList,args,kw)
		if iraf.Verbose>1:
			print "CL task run ", self.getName(), "("+self.getFullpath()+")"
			newParList.lpar()
		# create the list of parameter dictionaries to use
		self.setParDictList()
		# run the task using new par list
		oldValue = self._parDictList[0]
		self._parDictList[0] = (self._name,newParList.getParDict())
		try:
			# redirect the I/O
			resetList = iraf.redirApply(redirKW)
			# run the task
			self.runCode(newParList.getParList())
			changed = self.updateParList(newParList)
			if changed and (nosave==0):
				rv = self.save()
				if iraf.Verbose>1: print rv
		finally:
			# restore I/O
			iraf.redirReset(resetList, closeFHList)
			self._parDictList[0] = oldValue
		if iraf.Verbose>1: print 'Successful task termination'

	def runCode(self, parList=None, kw={}):
		"""Run the procedure with current parameters"""
		# add the searchable task object to keywords
		kw['taskObj'] = ParDictListSearch(self)
		if parList is None: parList = self.getParList()
		apply(self._clFunction, parList, kw)

	def getCode(self):
		"""Return a string with the Python code for this task"""
		self.initTask()
		return self._pycode.code

	def initTask(self,filehandle=None):
		"""Fill in full pathnames of files, read par file, compile CL code

		If filehandle is specified, reads CL code from there
		"""

		if filehandle is not None and self._filename:
			self._fullpath = iraf.Expand(self._filename)

		IrafTask.initTask(self)

		if filehandle is None:
			filehandle = self._fullpath

		if self._pycode is not None:
			# Python code already exists, but make sure file has not changed
			if cl2py.checkCache(filehandle, self._pycode): return
			if iraf.Verbose>1:
				print "Cached version of %s is out-of-date" % (self._name,)

		# translate code to python, compile it, and execute it (to define
		# the Python function in clDict)
		if iraf.Verbose>1:
			print "Compiling CL task %s" % (self._name,)

		self._pycode = cl2py.cl2py(filehandle,
			parlist=self._defaultParList, parfile=self._defaultParpath)
		scriptname = '<CL script %s.%s>' % (self._pkgname, self._name)
		self._codeObject = compile(self._pycode.code, scriptname, 'exec')
		clDict = {}
		exec self._codeObject in clDict
		self._clFunction = clDict[self._pycode.vars.proc_name]

		# get parameter list from CL code
		# This may replace an existing list -- that's OK since
		# the cl2py code has already checked it for consistency.
		self._defaultParList = self._pycode.vars.parList
		# use currentParList from .par file if exists and consistent
		if self._currentParpath:
			if not self._defaultParList.isConsistent(self._currentParList):
				sys.stderr.write("uparm parameter list `%s' inconsistent "
				  "with default parameters for %s `%s'\n" %
				  (self._currentParpath, self.__class__.__name__, self._name,))
				sys.stderr.flush()
				print 'default'
				self._defaultParList.lpar()
				print 'current'
				self._currentParList.lpar()
				#XXX just toss it for now -- later can try to merge new,old
				self._currentParpath = self._defaultParpath
				self._currentParList = copy.deepcopy(self._defaultParList)
		else:
			self._currentParList = copy.deepcopy(self._pycode.vars.parList)
			self._currentParpath = self._defaultParpath


# -----------------------------------------------------
# IRAF package class
# -----------------------------------------------------

class IrafPkg(IrafCLTask):

	"""IRAF package class (special case of IRAF task)"""

	def __init__(self, prefix, name, suffix, filename, pkgname, pkgbinary):
		IrafCLTask.__init__(self,prefix,name,suffix,filename,pkgname,pkgbinary)
		self._loaded = 0
		self._tasks = minmatch.MinMatchDict()
		self._pkgs = minmatch.MinMatchDict()

	def getLoaded(self):
		"""Returns true if this package has already been loaded"""
		return self._loaded

	def __getattr__(self, name, triedpkgs=None):
		"""Return the task 'name' from this package (if it exists).

		Also searches subpackages for the task.  triedpkgs is
		a dictionary with all the packages that have already been
		tried.  It is used to avoid infinite recursion when
		packages contain themselves.
		"""
		if name[:1] == '_': raise AttributeError(name)
		self.initTask()
		# return package parameter if it exists
		if self._currentParList.hasPar(name):
			return self._currentParList.get(name,native=1,mode=self.getMode())
		# else search for task with the given name
		if not self._loaded:
			raise AttributeError("Package " + self.getName() +
				" has not been loaded; no tasks are defined")
		fullname = self._tasks.get(name)
		if fullname: return iraf.getTask(fullname)
		# try subpackages
		if not triedpkgs: triedpkgs = {}
		triedpkgs[self] = 1
		for fullname in self._pkgs.values():
			p = iraf.getPkg(fullname)
			if p._loaded and (not triedpkgs.get(p)):
				try:
					return p.__getattr__(name,triedpkgs=triedpkgs)
				except AttributeError, e:
					pass
		raise AttributeError("Parameter "+name+" not found")

	def addTask(self, task, fullname):
		"""Add a task to the task list for this package

		Just store the name of the task to avoid cycles
		"""
		name = task.getName()
		self._tasks.add(name, fullname)
		# sub-packages get added to a separate list
		if isinstance(task, IrafPkg): self._pkgs.add(name, name)

	def run(self,*args,**kw):
		"""Load this package with the specified parameters"""
		self.initTask()

		if kw.has_key('_nosave'):
			nosave = kw['_nosave']
			del kw['_nosave']
		else:
			nosave = 0

		# Special _doprint keyword is used to control whether tasks are listed
		# after package has been loaded.  Default is to list them if cl.menus
		# is set, or not to list them if it is not set.
		if kw.has_key('_doprint'):
			doprint = kw['_doprint']
			del kw['_doprint']
		else:
			doprint = iraf.cl.menus

		# Special _hush keyword is used to suppress most output when loading
		# packages.  Default is to print output.
		# Implement by redirecting stdout to /dev/null (but don't override
		# other redirection requests)
		if kw.has_key('_hush'):
			if kw['_hush'] and \
			  not (kw.has_key('Stdout') or kw.has_key('StdoutAppend')):
				kw['Stdout'] = '/dev/null'
			del kw['_hush']

		redirKW, closeFHList = iraf.redirProcess(kw)
		# if already loaded, just add to iraf.loadedPath
		iraf.loadedPath.append(self)
		if not self._loaded:
			self._loaded = 1
			iraf.addLoaded(self)
			if iraf.Verbose>1:
				print "Loading pkg ",self.getName(), "("+self.getFullpath()+")",
				if self.hasParfile():
					print "par", self.getParpath(), \
						"["+`len(self.getParList())`+"] parameters",
				print
			# set parameters
			newParList = apply(self.setParList,args,kw)
			#XXX more args to add?
			#XXX redirKW['PkgName'] = self.getPkgname()
			#XXX redirKW['PkgBinary'] = self.getPkgbinary()
			menus = iraf.cl.menus
			iraf.cl.menus = 0
			# create the list of parameter dictionaries to use
			self.setParDictList()
			# run the task using new par list
			oldValue = self._parDictList[0]
			self._parDictList[0] = (self._name,newParList.getParDict())
			try:
				# redirect the I/O
				resetList = iraf.redirApply(redirKW)
				self.runCode(newParList.getParList())
				changed = self.updateParList(newParList)
				if changed and (nosave==0):
					rv = self.save()
					if iraf.Verbose>1: print rv
			finally:
				iraf.cl.menus = menus
				iraf.redirReset(resetList, closeFHList)
				self._parDictList[0] = oldValue
			# if other packages were loaded, put this on the
			# loadedPath list one more time
			if iraf.loadedPath[-1] != self:
				iraf.loadedPath.append(self)
			if doprint: iraf.listTasks(self)
			if iraf.Verbose>1:
				print "Done loading",self.getName()

# -----------------------------------------------------
# IRAF foreign task class
# -----------------------------------------------------

# regular expressions for parameter substitution
_re_foreign_par = re.compile(r'\$' +
					r'((?P<n>[0-9]+)' +
					r'|(?P<all>\*)' +
					r'|(\((?P<paren>[0-9]+)\))' +
					r'|(\((?P<allparen>\*)\))' +
					r')')

class IrafForeignTask(IrafTask):

	"""IRAF foreign task class"""

	def __init__(self, prefix, name, suffix, filename, pkgname, pkgbinary):
		IrafTask.__init__(self,prefix,name,suffix,filename,pkgname,pkgbinary)
		# check that parameters are consistent with foreign task:
		# - foreign flag set
		# - no parameter file
		if not self.getForeign():
			raise iraf.IrafError("Bad filename for foreign task %s: %s" %
				(self.getName(), filename))
		if self.hasParfile():
			if iraf.Verbose>0:
				print "Foreign task " + self.getName() + \
					" cannot have a parameter file"
			self._hasparfile = 0

	def run(self,*args,**kw):
		"""Run the task"""
		# Special Stdout, Stdin, Stderr keywords are used to redirect IO
		redirKW, closeFHList = iraf.redirProcess(kw)
		if len(kw)>0:
			raise ValueError('Illegal keyword parameters %s for task %s' %
				(kw.keys(), self._name,))
		# set parameters
		self._args = args
		self._nsub = 0
		# create command line
		cmdline = _re_foreign_par.sub(self.parSub,self._filename)
		if self._nsub==0 and args:
			# no argument substitution, just append all args
			cmdline = cmdline + ' ' + string.join(args,' ')
		if iraf.Verbose>1: print "Running foreign task", cmdline
		try:
			# redirect the I/O
			resetList = iraf.redirApply(redirKW)
			# create and run the subprocess
			subproc.systemRedir(cmdline)
		finally:
			iraf.redirReset(resetList, closeFHList)
		if iraf.Verbose>1: print 'Successful task termination'

	def parSub(self, mo):
		"""Substitute an argument for this match object"""
		self._nsub = self._nsub+1
		n = mo.group('n')
		if n is not None:
			# $n -- simple substitution
			n = int(n)
			if n>len(self._args):
				return ''
			elif n==0:
				return self._name
			else:
				return self._args[n-1]
		n = mo.group('paren')
		if n is not None:
			# $(n) -- expand IRAF virtual filenames
			n = int(n)
			if n>len(self._args):
				return ''
			elif n==0:
				return self._name
			else:
				return iraf.Expand(self._args[n-1])
		n = mo.group('all')
		if n is not None:
			# $* -- append all arguments
			return string.join(self._args,' ')
		n = mo.group('allparen')
		if n is not None:
			# $(*) -- append all arguments with virtual filenames converted
			return string.join(map(iraf.Expand,self._args),' ')
		raise iraf.IrafError("Cannot handle foreign string `%s' "
			"for task %s" % (self._filename, self._name))


# -----------------------------------------------------
# Utility function to split qualified names into components
# -----------------------------------------------------

def _splitName(qualifiedName):
	"""Split qualifiedName into components.

	qualifiedName looks like [[package.]task.]paramname[subscript][.field],
	where subscript is an index in brackets.  Returns a tuple with
	(package, task, paramname, subscript, field). IRAF one-based subscript
	is changed to Python zero-based subscript.
	"""
	slist = string.split(qualifiedName,'.')
	package = None
	task = None
	pindex = None
	field = None
	ip = len(slist)-1
	if ip>0 and slist[ip][:2] == "p_":
		field = slist[ip]
		ip = ip-1
	paramname = slist[ip]
	if ip > 0:
		ip = ip-1
		task = slist[ip]
		if ip > 0:
			ip = ip-1
			package = slist[ip]
			if ip > 0:
				raise iraf.IrafError("Illegal syntax for parameter: " +
					qualifiedName)

	# parse possible subscript

	pstart = string.find(paramname,'[')
	if pstart >= 0:
		try:
			pend = string.rindex(paramname,']')
			pindex = int(paramname[pstart+1:pend])-1
			paramname = paramname[:pstart]
		except:
			raise iraf.IrafError("Illegal syntax for array parameter: " +
				qualifiedName)
	return (package, task, paramname, pindex, field)

