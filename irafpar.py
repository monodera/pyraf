"""module 'irafpar.py' -- parse IRAF .par files and create lists of
IrafPar objects

$Id$

R. White, 1999 Jan 5
"""

import os, sys, string, re, irafgcur
from types import *

# -----------------------------------------------------
# IRAF parameter factory
# -----------------------------------------------------

_string_types = [ 's', 'f', 'struct', 'pset',
	'*imcur', '*struct', '*s', '*i', '*ukey' ]
_real_types = [ 'r', 'd' ]

def IrafParFactory(fields,strict=0):
	"""IRAF parameter factory

	Set the strict parameter to non-zero value to do stricter parsing
	(to find errors in .par files)"""

	orig_len = len(fields)
	if orig_len < 3:
		raise SyntaxError("Fewer than 3 fields in parameter line")
	type = fields[1]
	if type in _string_types:
		return IrafParS(fields,strict)
	elif type == "*gcur":
		return IrafParGCur(fields,strict)
	elif type in _real_types:
		return IrafParR(fields,strict)
	elif type == "i":
		return IrafParI(fields,strict)
	elif type == "b":
		return IrafParB(fields,strict)
	elif type == "ar":
		return IrafParAR(fields,strict)
	elif type == "ai":
		return IrafParAI(fields,strict)
	elif type[:1] == "a":
		raise SyntaxError("Cannot handle arrays of type "+type)
	else:
		raise SyntaxError("Cannot handle parameter type "+type)

# -----------------------------------------------------
# IRAF parameter base class
# -----------------------------------------------------

_getFieldList = ("p_name", "p_xtype", "p_mode", "p_prompt",
			"p_value", "p_filename", "p_maximum", "p_minimum")
_setFieldList = ("p_prompt", "p_value", "p_filename", "p_maximum", "p_minimum")

class IrafPar:
	"""IRAF parameter base class"""
	def __init__(self,fields,strict=0):
		orig_len = len(fields)
		if orig_len < 3:
			raise SyntaxError("Fewer than 3 fields in parameter line")
		#
		# all the attributes that are going to get defined (put them here
		# to make them easier to find)
		#
		self.name   = fields[0]
		self.type   = fields[1]
		self.mode   = fields[2]
		self.value  = None
		self.dim    = 1
		self.min    = None
		self.max    = None
		self.choice = None
		self.prompt = None

	def getPrompt(self):
		"""Interactively prompt for parameter value"""
		pstring = string.split(self.prompt,"\n")[0]
		if self.choice:
			schoice = [None]*len(self.choice)
			for i in xrange(len(self.choice)):
				schoice[i] = self.toString(self.choice[i])
			pstring = pstring + " (" + string.join(schoice,"|") + ")"
		elif self.min != None or self.max != None:
			pstring = pstring + " ("
			if self.min != None: pstring = pstring + self.toString(self.min)
			pstring = pstring + ":"
			if self.max != None: pstring = pstring + self.toString(self.max)
			pstring = pstring + ")"
		pstring = pstring + ": "
		print pstring,
		value = string.strip(sys.stdin.readline())
		# loop until we get an acceptable value
		while (1):
			try:
				self.set(value)
				return
			except ValueError, e:
				print e
			print pstring,
			value = string.strip(sys.stdin.readline())

	def get(self, field=None, index=None, prompt=1):
		"""Return value of this parameter as a string"""
		# prompt for query parameters unless prompt is set to zero
		if prompt and self.mode == "q": self.getPrompt()
		if index != None:
			if self.dim < 2:
				raise SyntaxError("Parameter "+self.name+" is not an array")
			try:
				return self.toString(self.value[index])
			except IndexError:
				raise SyntaxError("Illegal index [" + `index` +
					"] for array parameter " + self.name)

		if field: return self.getField(field)

		if self.dim == 1:
			return self.toString(self.value)
		else:
			# return blank-separated string of values for array
			sval = self.dim*[None]
			for i in xrange(self.dim):
				sval[i] = self.toString(self.value[i])
			return string.join(sval,' ')

	def toString(self, value):
		# convert a single (non-array) value of the appropriate type for this
		# parameter to a string
		if value == None:
			return ""
		else:
			return str(value)

	def getField(self, field):
		ffield = minMatch(field,_getFieldList)
		if not ffield:
			raise SyntaxError(
				"Unrecognized or unimplemented parameter field " +
				field + " for parameter " + self.name)
		elif len(ffield) > 1:
			raise SyntaxError(
				"Ambiguous parameter field " +
				field + " for parameter " + self.name +
				"\nCould be any of " + `ffield`)
		field = ffield[0]
		if field == "p_name": return self.name
		elif field == "p_xtype": return self.type
		elif field == "p_mode": return self.mode
		elif field == "p_prompt": return self.prompt
		elif field == "p_value": return self.get()
		elif field == "p_filename": return str(self.value)
		elif field == "p_maximum": return self.toString(self.maximum)
		elif field == "p_minimum":
			if self.choice != None:
				schoice = [None]*len(self.choice)
				for i in xrange(len(self.choice)):
					schoice[i] = self.toString(self.choice[i])
				schoice = "|" + string.join(schoice,"|") + "|"
				return schoice
			else:
				return self.toString(self.minimum)
		else:
			# XXX unimplemented fields:
			# p_type: different than p_xtype?
			# p_length: length in bytes? IRAF words? something else?
			# p_default: from task parameter file (as opposed to current
			#    .par file)?
			raise RuntimeError("Program bug in IrafPar.getField()")

	def set(self, value, field=None, index=None, check=1):
		"""Set value of this parameter from a string or other value.
		Field is optional parameter field (p_prompt, p_minimum, etc.)
		Index is optional array index (zero-based).  Set check=0 to
		assign the value without checking to see if it is within
		the min-max range or in the choice list."""
		if index != None:
			if self.dim < 2:
				raise SyntaxError("Parameter "+self.name+" is not an array")
			try:
				value = self.coerceOneValue(value)
				if check:
					self.value[index] = self.checkOneValue(value)
				else:
					self.value[index] = value
				return
			except IndexError:
				raise SyntaxError("Illegal index [" + `index` +
					"] for array parameter " + self.name)
		if field:
			self.setField(value,field,check=check)
		else:
			if check:
				self.value = self.checkValue(value)
			else:
				self.value = self.coerceValue(value)
			return

	def setField(self, value, field, check=1):
		ffield = minMatch(field,_setFieldList)
		if not ffield:
			raise SyntaxError("Cannot set field " + field +
				" for parameter " + self.name)
		elif len(ffield) > 1:
			raise SyntaxError("Ambiguous field " + field +
				" for parameter " + self.name +
				"\nCould be any of " + `ffield`)
		field = ffield[0]
		if field == "p_prompt":
			self.prompt = _stripQuote(value)
		elif field == "p_value":
			self.set(value,check=check)
		elif field == "p_filename":
			# this is only relevant for list parameters (*imcur, *gcur, etc.)
			self.value = _stripQuote(value)
		elif field == "p_maximum":
			self.maximum = self.coerceOneValue(value)
		elif field == "p_minimum":
			if type(value) == StringType and '|' in value:
				value = _stripQuote(value)
				# new choice list
				clist = _getChoice(value)
				newchoice = len(clist)*[0]
				for i in xrange(len(clist)):
					newchoice[i] = self.coerceOneValue(clist[i])
				self.choice = newchoice
			else:
				self.minimum = self.coerceOneValue(value)
		else:
			raise RuntimeError("Program bug in IrafPar.setField()")

	# raises exception if value is not permitted for this parameter
	# otherwise returns the value (converted to right type)
	def checkValue(self,value,strict=0):
		v = self.coerceValue(value,strict)
		if self.dim == 1:
			return self.checkOneValue(v,strict)
		else:
			for i in xrange(self.dim): self.checkOneValue(v[i])
			return v

	# checks single value to see if it is in range or choice list
	# ignores indirection strings starting with ")"
	# assumes v has already been converted to right value by
	# coerceOneValue
	# returns value if OK, or raises ValueError if not OK
	def checkOneValue(self,v,strict=0):
		if v == None or v == "" or \
				((type(v) is StringType) and (v[0] == ")")):
			return v
		elif self.choice != None and not (v in self.choice):
			raise ValueError("Value '" + str(v) + "' is not in choice list for " +
				self.name)
		elif (self.min != None and v < self.min) or (self.max != None and v > self.max):
			raise ValueError("Value '" + str(v) + "' is out of min-max range for " +
				self.name)
		return v

	# coerce a scalar parameter to the appropriate type
	# should accept None or null string
	def coerceOneValue(self,value,strict=0):
		raise RuntimeError("Bug: base class IrafPar cannot be used directly")

	# coerce parameter to appropriate type
	# should accept None or null string
	def coerceValue(self,value,strict=0):
		if self.dim == 1:
			return self.coerceOneValue(value,strict)
		if (type(value) not in [ListType,TupleType]) or len(value) != self.dim:
			raise ValueError("Value must be a " + `self.dim` + \
				"-element integer array for "+self.name)
		v = self.dim*[0]
		for i in xrange(self.dim):
			v[i] = self.coerceOneValue(value[i],strict)
		return v

	# return pretty list description of parameter
	def pretty(self,verbose=0):
		# split prompt lines and add blanks in later lines to align them
		plines = string.split(self.prompt,'\n')
		for i in xrange(len(plines)-1): plines[i+1] = 32*' ' + plines[i+1]
		plines = string.join(plines,'\n')
		if self.mode == "h":
			s = "%13s = %-15s %s" % ("("+self.name,
						self.get(prompt=0)+")", plines)
		else:
			s = "%13s = %-15s %s" % (self.name,
						self.get(prompt=0), plines)
		if not verbose: return s

		if self.choice != None:
			s = s + "\n" + 32*" " + "|"
			nline = 33
			for i in xrange(len(self.choice)):
				sch = str(self.choice[i]) + "|"
				s = s + sch
				nline = nline + len(sch) + 1
				if nline > 80:
					s = s + "\n" + 32*" " + "|"
					nline = 33
		elif self.min != None or self.max != None:
			s = s + "\n" + 32*" "
			if self.min != None:
				s = s + str(self.min) + " <= "
			s = s + self.name
			if self.max != None:
				s = s + " <= " + str(self.max)
		return s

	# return readable description of parameter
	def __str__(self):
		s = "<IrafPar " + self.name + " " + self.type
		if self.dim > 1: s = s + "[" + str(self.dim) + "]"
		s = s + " " + self.mode + " " + `self.value`
		if self.choice != None:
			s = s + " |"
			for i in xrange(len(self.choice)):
				s = s + str(self.choice[i]) + "|"
		else:
			s = s + " " + `self.min` + " " + `self.max`
		s = s + ' "' + self.prompt + '">'
		return s

# -----------------------------------------------------
# IRAF string parameter class
# -----------------------------------------------------

class IrafParS(IrafPar):
	"""IRAF string parameter class"""
	def __init__(self,fields,strict=0):
		IrafPar.__init__(self,fields,strict)
		orig_len = len(fields)
		while len(fields) < 7: fields.append("")
		#
		self.value = fields[3]
		# string (s) can have choice of values; min,max must be null for others
		# if not in strict mode, allow file (f) to act just like string (s)
		if self.type == "s" or ((not strict) and (self.type == "f")):
			# only min can be defined and it must have choices
			if fields[4] != "":
				s = string.strip(fields[4])
				self.choice = _getChoice(s,strict)
			if fields[5] != "":
				if orig_len < 7:
					raise SyntaxError(
						"Illegal max value for string type parameter " + 
						self.name + " (possibly missing comma)")
				else:
					raise SyntaxError(
						"Illegal max value for string type parameter " + self.name)
		else:
			# otherwise, min & max must be blank
			if fields[4] != "" or fields[5] != "":
				if orig_len < 7:
					raise SyntaxError("Illegal min/max/choice values for type " + \
						self.type + " for parameter " + self.name +
						" (possibly missing comma)")
				else:
					raise SyntaxError("Illegal min/max/choice values for type " + \
						self.type + " for parameter " + self.name)
		self.prompt = fields[6]
		# check parameter to see if it is correct
		self.checkValue(self.value,strict)
	def coerceOneValue(self,value,strict=0):
		if value == None:
			return ""
		elif type(value) is StringType:
			# strip double quotes
			return _stripQuote(value)
		else:
			return str(value)

# -----------------------------------------------------
# Utility function to strip double quotes off string
# -----------------------------------------------------

def _stripQuote(value):
	if value[:1] == '"':
		value = value[1:]
		if value[-1:] == '"':
			value = value[:-1]
	return value

# -----------------------------------------------------
# IRAF gcur (graphics cursor) parameter class
# -----------------------------------------------------

# XXX Need to upgrade this to handle file list inputs too.
# That is a bit tricky because we need to initialize the
# input list every time we start a new task.  Will need
# to add an initialization step for all list parameters.
# Probably should handle all list parameters at the same time.

class IrafParGCur(IrafParS):
	"""IRAF graphics cursor parameter class"""
	def __init__(self,fields,strict=0):
		IrafParS.__init__(self,fields,strict)
	def get(self, field=None, index=None, prompt=1):
		"""Return graphics cursor value"""
		if index or (prompt != 1):
			raise SyntaxError("Parameter " + self.name +
				" is graphics cursor, cannot use index or prompt")
		if field: return self.getField(field)
		return irafgcur.gcur()

# -----------------------------------------------------
# IRAF boolean parameter class
# -----------------------------------------------------

class IrafParB(IrafPar):
	"""IRAF boolean parameter class"""
	def __init__(self,fields,strict=0):
		IrafPar.__init__(self,fields,strict)
		orig_len = len(fields)
		while len(fields) < 7: fields.append("")
		#
		self.value = self.coerceValue(fields[3],strict)
		# other, min & max must be blank
		if fields[4] != "" or fields[5] != "":
			if orig_len < 7:
				raise SyntaxError("Illegal min/max/choice values for type " + \
					self.type + " for parameter " + self.name +
					" (possibly missing comma)")
			else:
				raise SyntaxError("Illegal min/max/choice values for type " + \
					self.type + " for parameter " + self.name)
		self.prompt = fields[6]
		if self.min != None and self.max != None and self.max < self.min:
			raise SyntaxError("Max " + str(self.max) + " is less than min " + \
				str(self.min) + " for parameter " + self.name)
		# check parameter to see if it is correct
		self.checkValue(self.value,strict)

	def toString(self, value):
		if value == None:
			return ""
		elif type(value) == StringType:
			# presumably an indirection value ')task.name'
			return value
		else:
			strval = ["no", "yes"]
			return strval[value]

	# accepts integer values 0,1 or string 'yes','no' and variants
	def coerceOneValue(self,value,strict=0):
		if value == None or value == 0 or value == 1: return value
		tval = type(value)
		if tval is StringType:
			v2 = string.strip(value)
			if v2 == "":
				return None
			elif v2[0] == ")":
				# assume this is indirection -- for now just save it as a string
				return v2
			# even more strict would just accept lower-case "yes", "no"
			ff = string.lower(v2)
			if ff == "no" or ff == "n":
				return 0
			elif ff == "yes" or ff == "y":
				return 1
		elif tval is FloatType:
			# try converting to integer
			try:
				ival = int(value)
				if (ival == value) and (ival == 0 or ival == 1):
					return ival
			except Exception:
				pass
		raise ValueError("Illegal boolean value "+`value` +
			" for parameter " + self.name)

# -----------------------------------------------------
# IRAF integer parameter class
# -----------------------------------------------------

class IrafParI(IrafPar):
	"""IRAF integer parameter class"""
	def __init__(self,fields,strict=0):
		IrafPar.__init__(self,fields,strict)
		orig_len = len(fields)
		while len(fields) < 7: fields.append("")
		#
		self.value = self.coerceValue(fields[3],strict)
		s = string.strip(fields[4])
		if '|' in s:
			clist = _getChoice(s,strict)
			self.choice = len(clist)*[0]
			for i in xrange(len(clist)):
				self.choice[i] = self.coerceOneValue(clist[i],strict)
			if fields[5] != "":
				if orig_len < 7:
					raise SyntaxError(
						"Max value illegal when choice list given" +
						" for parameter " + self.name +
						" (possibly missing comma)")
				else:
					raise SyntaxError(
						"Max value illegal when choice list given" +
						" for parameter " + self.name)
		else:
			self.min = self.coerceOneValue(fields[4],strict)
			self.max = self.coerceOneValue(fields[5],strict)
		self.prompt = fields[6]
		if self.min != None and self.max != None and self.max < self.min:
			raise SyntaxError("Max " + str(self.max) + " is less than min " + \
				str(self.min) + " for parameter " + self.name)
		# check parameter to see if it is correct
		self.checkValue(self.value,strict)

	def toString(self, value):
		if value == None:
			return "INDEF"
		else:
			return str(value)

	# coerce value to integer
	def coerceOneValue(self,value,strict=0):
		if value == None: return None
		tval = type(value)
		if tval is IntType:
			return value
		elif tval is FloatType:
			# try converting to integer
			try:
				ival = int(value)
				if (ival == value): return ival
			except Exception:
				pass
			raise ValueError("Illegal integer value " + `value` +
				" for parameter " + self.name)
		elif tval is StringType:
			s2 = string.strip(value)
			if s2 == "" or ((not strict) and (string.upper(s2) == "INDEF")) or \
					(strict and (s2 == "INDEF")):
				return None
			elif s2[0] == ")":
				# assume this is indirection -- for now just save it as a string
				return s2
			elif s2[-1:] == "x":
				# hexadecimal
				return string.atoi(s2[:-1],16)
			else:
				return int(s2)

# -----------------------------------------------------
# IRAF integer array parameter class
# -----------------------------------------------------

class IrafParAI(IrafParI):
	"""IRAF integer array parameter class"""
	def __init__(self,fields,strict=0):
		IrafPar.__init__(self,fields,strict)
		orig_len = len(fields)
		while len(fields) < 7: fields.append("")
		# for array parameter, get dimensions from normal values field
		# and get values from fields after prompt
		ndim = int(fields[3])
		if ndim != 1:
			raise SyntaxError("Cannot handle multi-dimensional arrays" +
				" for parameter " + self.name)
		self.dim = int(fields[4])
		while len(fields) < 9+self.dim: fields.append("")
		if len(fields) > 9+self.dim:
			raise SyntaxError("Too many values for array" +
				" for parameter " + self.name)
		#
		self.value = self.coerceValue(fields[9:9+self.dim],strict)
		s = string.strip(fields[6])
		if '|' in s:
			clist = _getChoice(s,strict)
			self.choice = len(clist)*[0]
			for i in xrange(len(clist)):
				self.choice[i] = self.coerceOneValue(clist[i],strict)
			if fields[7] != "":
				if orig_len < 9:
					raise SyntaxError("Max value illegal when choice list given" +
						" for parameter " + self.name +
						" (possibly missing comma)")
				else:
					raise SyntaxError("Max value illegal when choice list given" +
						" for parameter " + self.name)
		else:
			self.min = self.coerceOneValue(fields[6],strict)
			self.max = self.coerceOneValue(fields[7],strict)
		self.prompt = fields[8]
		if self.min != None and self.max != None and self.max < self.min:
			raise SyntaxError("Max " + str(self.max) + " is less than min " + \
				str(self.min) + " for parameter " + self.name)
		# check parameter to see if it is correct
		self.checkValue(self.value,strict)

# -----------------------------------------------------
# IRAF real parameter class
# -----------------------------------------------------

_re_d = re.compile(r'[Dd]')
_re_colon = re.compile(r':')

class IrafParR(IrafPar):
	"""IRAF real parameter class"""
	def __init__(self,fields,strict=0):
		IrafPar.__init__(self,fields,strict)
		orig_len = len(fields)
		while len(fields) < 7: fields.append("")
		#
		self.value = self.coerceValue(fields[3],strict)
		s = string.strip(fields[4])
		if '|' in s:
			raise SyntaxError("Choice list not allowed for float values" +
				" for parameter " + self.name)
		else:
			self.min = self.coerceOneValue(fields[4],strict)
			self.max = self.coerceOneValue(fields[5],strict)
		self.prompt = fields[6]
		if self.min != None and self.max != None and self.max < self.min:
			raise SyntaxError("Max " + str(self.max) + " is less than min " +
				" for parameter " + self.name +
				str(self.min))
		# check parameter to see if it is correct
		self.checkValue(self.value,strict)

	def toString(self, value):
		if value == None:
			return "INDEF"
		else:
			return str(value)

	# coerce value to real
	def coerceOneValue(self,value,strict=0):
		if value == None: return None
		tval = type(value)
		if tval is FloatType:
			return value
		elif tval in [LongType,IntType]:
			return float(value)
		elif tval is StringType:
			s2 = string.strip(value)
			if s2 == "" or ((not strict) and (string.upper(s2) == "INDEF")) or \
					(strict and (s2 == "INDEF")):
				return None
			elif s2[0] == ")":
				# assume this is indirection -- for now just save it as a string
				return s2
			else:
				# allow +dd:mm:ss.s sexagesimal format for floats
				value = 0.0
				vscale = 1.0
				vsign = 1
				i1 = 0
				mm = _re_colon.search(s2)
				if mm != None:
					if s2[0] == "-":
						i1 = 1
						vsign = -1
					elif s2[0] == "+":
						i1 = 1
					while mm != None:
						i2 = mm.start()
						value = value + int(s2[i1:i2])/vscale
						i1 = i2+1
						vscale = vscale*60.0
						mm = _re_colon.search(s2,i1)
				# special handling for d exponential notation
				mm = _re_d.search(s2,i1)
				if mm == None:
					return vsign*(value + float(s2[i1:])/vscale)
				else:
					return vsign*(value + \
						float(s2[i1:mm.start()]+"E"+s2[mm.end():])/vscale)


# -----------------------------------------------------
# IRAF real array parameter class
# -----------------------------------------------------

class IrafParAR(IrafParR):
	"""IRAF real array parameter class"""
	def __init__(self,fields,strict=0):
		IrafPar.__init__(self,fields,strict)
		orig_len = len(fields)
		while len(fields) < 7: fields.append("")
		# for array parameter, get dimensions from normal values field
		# and get values from fields after prompt
		ndim = int(fields[3])
		if ndim != 1:
			raise SyntaxError("Cannot handle multi-dimensional arrays" +
				" for parameter " + self.name)
		self.dim = int(fields[4])
		while len(fields) < 9+self.dim: fields.append("")
		if len(fields) > 9+self.dim:
			raise SyntaxError("Too many values for array" +
				" for parameter " + self.name)
		#
		self.value = self.coerceValue(fields[9:9+self.dim],strict)
		s = string.strip(fields[6])
		if '|' in s:
			raise SyntaxError("Choice list not allowed for float values" +
				" for parameter " + self.name)
		else:
			self.min = self.coerceOneValue(fields[6],strict)
			self.max = self.coerceOneValue(fields[7],strict)
		self.prompt = fields[8]
		if self.min != None and self.max != None and self.max < self.min:
			raise SyntaxError("Max " + str(self.max) + " is less than min " + \
				str(self.min) + " for parameter " + self.name)
		# check parameter to see if it is correct
		self.checkValue(self.value,strict)

# -----------------------------------------------------
# utility routine for parsing choice string
# -----------------------------------------------------

_re_choice = re.compile(r'\|')

def _getChoice(s,strict=0):
	if strict and ((s[0] != "|") or (s[-1] != "|")):
		raise SyntaxError("Choice string does not start and end with '|'")
	if s[0] == "|":
		i1 = 1
	else:
		i1 = 0
	clist = []
	mm = _re_choice.search(s,i1)
	while mm != None:
		i2 = mm.start()
		clist.append(s[i1:i2])
		i1 = mm.end()
		mm = _re_choice.search(s,i1)
	if i1 < len(s):
		clist.append(s[i1:])
	return clist

# -----------------------------------------------------
# utility routine for minimum match from list of strings
# -----------------------------------------------------

# this is generally useful and ought to be moved somewhere else...

def minMatch(svalue,slist):
	"""Search for string svalue in list of strings slist, allowing
	minimum match so that svalue may match the beginning of the
	list entries.  Returns a list with all the matching values from
	slist (empty if none.)"""

	slen = len(svalue)
	n = len(slist)
	retlist = []
	for i in xrange(len(slist)):
		if svalue == slist[i][:slen]:
			retlist.append(slist[i])
	return retlist

# -----------------------------------------------------
# Read IRAF .par file and return list of parameters
# -----------------------------------------------------

# Parameter file is basically comma-separated fields, but
# with some messy variations involving embedded quotes
# and the ability to break the final field across lines.

def readpar(filename,strict=0):
	"""Read IRAF .par file and return list of parameters"""

	# Patterns that match a quoted string with embedded \" or \'
	# From Freidl, Mastering Regular Expressions, p. 176.
	#
	# Modifications:
	# - I'm using the "non-capturing" parentheses (?:...) where
	#   possible; I only capture the part of the string between
	#   the quotes.
	# - Match leading white space and optional trailing comma.
	# - Pick up any non-whitespace between the closing quote and
	#   the comma or end-of-line (which is a syntax error.)
	#   Any matched string gets captured into djunk or sjunk
	#   variable, depending on which quotes were matched.

	whitespace = r'[ \t]*'
	optcomma = r',?'
	noncommajunk = r'[^,]*'
	double = whitespace + r'"(?P<double>[^"\\]*(?:\\.[^"\\]*)*)"' + whitespace + \
		r'(?P<djunk>[^,]*)' + optcomma
	single = whitespace + r"'(?P<single>[^'\\]*(?:\\.[^'\\]*)*)'" + whitespace + \
		r'(?P<sjunk>[^,]*)' + optcomma

	# Comma-terminated string that doesn't start with quote
	# Match explanation:
	# - match leading white space 
	# - if end-of-string then done with capture
	# - elif lookahead == comma then done with capture
	# - else match not-[comma | blank | quote] followed
	#     by string of non-commas; then done with capture
	# - match trailing comma if present
	#
	# Trailing blanks do get captured (which I think is
	# the right thing to do)

	comma = whitespace + r"(?P<comma>$|(?=,)|(?:[^, \t'" + r'"][^,]*))' + optcomma

	# Combined pattern

	field = '(?:' + comma + ')|(?:' + double + ')|(?:' + single + ')'
	re_field = re.compile(field,re.DOTALL)

	# Pattern that matches trailing backslashes at end of line
	re_bstrail = re.compile(r'\\*$')

	# Pattern that matches unclosed quote at end of line, indicating need
	# to read another line.  This can only be used after all other strings
	# have been removed.  (This could be made more clever.)  Apparently
	# only double-quoted strings are allow to extend across lines
	re_unclosed = re.compile('"')

	param_dict = {}
	param_list = []
	fh = open(os.path.expanduser(filename),'r')
	line = fh.readline()
	while line != "":
		# strip whitespace (including newline) off both ends
		line = string.strip(line)
		# skip comments and blank lines
		# "..." is weird line that occurs in cl.par
		if len(line)>0 and line[0] != '#' and line != "...":
			# Append next line if this line ends with continuation character.
			while line[-1:] == "\\":
				# odd number of trailing backslashes means this is continuation
				if (len(re_bstrail.search(line).group()) % 2 == 1):
					line = line[:-1] + string.rstrip(fh.readline())
				else:
					break
			flist = []
			i1 = 0
			while len(line) > i1:
				mm = re_field.match(line,i1)
				if mm == None:
					# Failure occurs only for unmatched leading quote.
					# Append more lines to get quotes to match.  (Probably
					# want to restrict this behavior to only the description
					# field.)
					while mm == None:
						nline = fh.readline()
						if nline == "":
							raise SyntaxError(filename + "\n" + line + "\n" + \
								"Unmatched quote")
						line = line + '\n' + string.rstrip(nline)
						mm = re_field.match(line,i1)
				if mm.group('comma') != None:
					g = mm.group('comma')
					if strict:
						# check for trailing quote in unquoted string
						if g[-1:] == '"' or g[-1:] == "'":
							raise SyntaxError(filename + "\n" + line + "\n" + \
								"Unquoted string has trailing quote")
				elif mm.group('double') != None:
					if mm.group('djunk'):
						raise SyntaxError(filename + "\n" + line + "\n" + \
					 		"Non-blank follows quoted string")
					g = mm.group('double')
				elif mm.group('single') != None:
					if mm.group('sjunk'):
						raise SyntaxError(filename + "\n" + line + "\n" + \
					 		"Non-blank follows quoted string")
					g = mm.group('single')
				else:
					raise SyntaxError(filename + "\n" + line + "\n" + \
						"Huh? mm.groups()="+`mm.groups()`+"\n" + \
						"Bug: doesn't match single, double or comma??")
				flist.append(g)
				# move match pointer
				i1 = mm.end()
			try:
				par = IrafParFactory(flist,strict)
			except StandardError, exc:
				raise SyntaxError(filename + "\n" + line + "\n" + \
					str(flist) + "\n" + str(exc))
			if param_dict.has_key(par.name):
				raise SyntaxError(filename + "\n" + line + "\n" + \
					"Duplicate parameter "+par.name)
			param_dict[par.name] = par
			param_list.append(par)
		line = fh.readline()
	# add special $nargs parameter
	if not param_dict.has_key("$nargs"):
		try:
			flist = ["$nargs","i","h","0"]
			par = IrafParFactory(flist,strict)
		except StandardError, exc:
			raise SyntaxError(filename + "\n" + 
				"Error creating $nargs parameter\n" + str(exc))
		param_dict[par.name] = par
		param_list.append(par)
	return param_list


