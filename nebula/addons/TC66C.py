#!/usr/bin/env python3
#MIT License
#
#Copyright (c) 2022 TheHWcave
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in all
#copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#SOFTWARE.

#
# 19-Jan-2022: fixed error that resistance is reported in 0.1 Ohm units, not 0.01 Ohm 
#
import serial,argparse,math,struct,sys
from Crypto.Cipher import AES
from collections import namedtuple
from time import sleep,time,localtime,strftime,monotonic
import os
import asyncio
					


class TC66C:
	
	_SIF : None
	_AES : None
	
	PollData = namedtuple('PollData',['Name','Version','SN','Runs',
									  'Volt','Current','Power',
									  'Resistance',
									  'G0_mAh','G0_mWh','G1_mAh','G1_mWh',
									  'Temp','D_plus','D_minus'])	
										
	RecData = namedtuple('RecData',  ['Volt','Current'])
											
			
		

	def __init__(self,logger, port_dev=None):
		self._logger = logger
		self._cumulative_energy = 0
		self._current_power = 0
		self._detailed_power_consumption = []
		STATIC_KEY = [0x58, 0x21, 0xfa, 0x56, 0x01, 0xb2, 0xf0, 0x26,
					  0x87, 0xff, 0x12, 0x04, 0x62, 0x2a, 0x4f, 0xb0,
					  0x86, 0xf4, 0x02, 0x60, 0x81, 0x6f, 0x9a, 0x0b,
					  0xa7, 0xf1, 0x06, 0x61, 0x9a, 0xb8, 0x72, 0x88]
		
		if port_dev == None:
			port_dev = DEFPORT
		try:
			self._SIF = serial.Serial(
				port=port_dev,
				baudrate=115200,
				bytesize=8,
				parity='N',
				stopbits=2,
				xonxoff = 0,
				rtscts = 0,
				dsrdtr = 1,
				timeout=5)
			sleep(1.0)
		except Exception as e:
			print(f"failed to open {port_dev} : {e}")
		
		self._AES = AES.new(bytes(STATIC_KEY),AES.MODE_ECB)

	def Poll(self):
		"""
			Polls the TC66C for new data and returns it in form of 
			a PollData record
			
			The data comes in a 192 byte package AES encrypted
		"""
		if not self._SIF.isOpen():
			self._SIF.open()
		self.SendCmd('getva')
	
		buf= self._SIF.read(192)
		try:
			data = self._AES.decrypt(buf)
		except:
			print('decrypt error')
		
		#
		# The data is returned in three 64 byte packs called 
		# pac1,pac2 and pac3
		# 
		PAC1_ID   = 0 	# 'pac1'  
		PAC1_NAME = 1 	# 'TC66'
		PAC1_VERS = 2 	# '1.14'
		PAC1_SN   = 3 	# serial number
		PAC1_RUNS = 11	# number of runs
		PAC1_VOLT = 12	# volts in 100uV 
		PAC1_AMPS = 13	# current in 10uA
		PAC1_PWR  = 14	# power in 100uW
		PAC1_CSUM = 15	# checksum for pac1
		
		PAC2_ID   = 0 	# 'pac2'
		PAC2_RES  = 1 	# resistance in 0.1 ohm
		PAC2_G0mAh= 2	# group 0 mAh
		PAC2_G0mWh= 3	# group 0 mWh
		PAC2_G1mAh= 4	# group 1 mAh
		PAC2_G1mWh= 5	# group 1 mAh
		PAC2_TSIGN= 6	# temperature sign  1 = negative
		PAC2_TVAL = 7	# temperature value in deg C
		PAC2_DP   = 8	# d plus voltage in 10 mV
		PAC2_DM   = 9	# d minus voltage in 10 mV
		PAC2_CSUM =15	# checksum for pac2
		
		PAC3_ID   = 0	# 'pac3'
		PAC3_CSUM =15	# checksum for pac3
		
		
		pac1 = struct.unpack('<4s4s4s13I',data[0:64])
		pac2 = struct.unpack('<4s15I',data[64:128])
		pac3 = struct.unpack('<4s15I',data[128:192])
		#print(pac1)
		#print(pac2)
		#print(pac3)
		
		if pac2[PAC2_TSIGN] == 1:
			tsign = -1
		else:
			tsign = 1
			
		pd = self.PollData(
			Name		= pac1[PAC1_NAME].decode(),
			Version 	= pac1[PAC1_VERS].decode(),
			SN			= pac1[PAC1_SN],
			Runs		= pac1[PAC1_RUNS],
			Volt		= float(pac1[PAC1_VOLT])*1E-4,
			Current	= float(pac1[PAC1_AMPS])*1E-5,
			Power		= float(pac1[PAC1_PWR])*1E-4,
			Resistance	= float(pac2[PAC2_RES])*1E-1,
			G0_mAh		= pac2[PAC2_G0mAh],
			G0_mWh		= pac2[PAC2_G0mWh],
			G1_mAh		= pac2[PAC2_G1mAh],
			G1_mWh		= pac2[PAC2_G1mWh],
			Temp		= pac2[PAC2_TVAL] * tsign,
			D_plus		= float(pac2[PAC2_DP])*1E-2,
			D_minus		= float(pac2[PAC2_DM])*1E-2)
		
	
		return pd
		
	def SendCmd(self,msg):
		"""
			sends a command string to the TC66C. There are only 7 valid ones (so far):
			
				query	response   4 bytes  'firm' or 'boot'
				getva	response 192 bytes  (see Poll function)
				gtrec	response variable 	(see GetRec function)
				lastp	response   0 bytes	(previous page on the TC66 display)
				nextp	response   0 bytes	(next page on the TC66 display)
				rotat	response   0 bytes	(rotate TC66 screen)
				update	response   5 bytes	'uprdy' = prepare to load new firmware
		"""
		self._SIF.write(msg.encode('ascii'))
		return 
	
	def log(self, time, power, cumulative_energy):
		resources = {
			"Power/Power Consumption (W)": power,
			"Power/Total Energy (J)": cumulative_energy,
		}
		#print(f"logging: time: {time}, cumulative_energy: {cumulative_energy}")   
		self._logger.log_data(resources, step=time)
		
	
	async def start(self):
		start = monotonic()
		now = monotonic()-start
		try:			
			while True:
				now = monotonic()-start
				pd = self.Poll()
				self._current_power = pd.Power
				self._detailed_power_consumption.append(self._current_power)
				self._cumulative_energy += self._current_power
					
				elapsed = (monotonic()-start) - now
				if elapsed < 1:
					await asyncio.sleep(1 - elapsed)
		except KeyboardInterrupt:
			print("Finished")		
			
	def current_power(self):
		return self._current_power
	
	def cumulative_energy(self):
		return self._cumulative_energy
	
	def detailed_power_consumption(self):
		return self._detailed_power_consumption
	
	
