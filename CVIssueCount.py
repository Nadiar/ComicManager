#
#CVIssueCount.py
#
#Author: Quinyd
#
#Description: Complete Story Arc with the Comic Vine info
#
#Versions:
#               0.1 First version
#               0.2 Added Progressbar, start and cancel buttons  
#               0.3 Added issue count        
#
#ComicRack Declarations
#
#@Name  CVIssueCount
#@Hook  Books
#@Key   CVIssueCount
#@PCount 0

# $ cd "..\..\Program Files\ComicRack\
# $ ComicRack.exe -ssc

from __future__ import unicode_literals

import clr, re, sys, os, urlparse, time

from System.Diagnostics import Process
clr.AddReference("System.xml")
import System
from System import *
from System.IO import *
from System.Collections import *
from System.Threading import *
from System.Net import *
from System.Text import *

clr.AddReference('System')
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Drawing
import System.Windows.Forms

from System.Drawing import *
from System.Windows.Forms import *

clr.AddReference('System.Drawing')
from System.Drawing import Point, Size, ContentAlignment, Color, SystemColors, Icon
clr.AddReference('System.Threading')
from System.Threading import *
from datetime import datetime
import ssl, urllib
from System.ComponentModel import BackgroundWorker


stop=False

def CVIssueCount(books):
    if books:
        f = CVIssueCountForm(books)
        r = f.ShowDialog()
    else:
        MessageBox.Show("No books selected")
        return

class CVIssueCountForm(Form):
    def __init__(self, books):
        self.InitializeComponent()
        self.books = books
        self.percentage = 1.0/len(books)*100
        self.progresspercent = 0.0
        self.stop = False

    def InitializeComponent(self):
        self._label1 = System.Windows.Forms.Label()
        self._Okay = System.Windows.Forms.Button();
        self._Cancel = System.Windows.Forms.Button();
        #resultLabel = System.Windows.Forms.Label();
        self._progress = System.Windows.Forms.ProgressBar();
        self.worker = BackgroundWorker();
        self.SuspendLayout()

        self.worker.WorkerSupportsCancellation = True
        self.worker.WorkerReportsProgress = True
        self.worker.DoWork += self.DoWork
        self.worker.ProgressChanged += self.ReportProgress
        self.worker.RunWorkerCompleted += self.WorkerCompleted
        
        self._progress.Location = System.Drawing.Point(12, 114)
        self._progress.Size = System.Drawing.Size(456, 17)
        self._progress.TabIndex = 4
        # 
        # label1
        # 
        self._label1.AutoSize = True
        self._label1.Location = System.Drawing.Point(12, 53)
        self._label1.Name = "label1"
        self._label1.Size = System.Drawing.Size(16, 13)
        self._label1.TabIndex = 3
        self._label1.Text = "Start searching Comicvine for issue counts using the 'Start' button"
        # 
        # Okay
        # 
        self._Okay.Location = System.Drawing.Point(312, 137)
        self._Okay.Name = "Okay"
        self._Okay.Size = System.Drawing.Size(75, 23)
        self._Okay.TabIndex = 5
        self._Okay.Text = "Start"
        self._Okay.UseVisualStyleBackColor = True
        self._Okay.Click += self.OkayClicked
        # 
        # Cancel
        # 
        self._Cancel.Location = System.Drawing.Point(393, 137)
        self._Cancel.Name = "Cancel"
        self._Cancel.Size = System.Drawing.Size(75, 23)
        self._Cancel.TabIndex = 6
        self._Cancel.Text = "Cancel"
        self._Cancel.Enabled = False
        self._Cancel.UseVisualStyleBackColor = True
        self._Cancel.Click += self.CancelClicked

        self.ClientSize = System.Drawing.Size(483, 170)
        self.Controls.Add(self._Cancel)
        self.Controls.Add(self._Okay)
        self.Controls.Add(self._progress)
        self.Controls.Add(self._label1)
        self.Name = "CVIssueCount"
        self.Text = "Get issue Count from CV"
        self.MinimizeBox = False
        self.MaximizeBox = False
        self.AcceptButton = self._Okay
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterParent

        self.ResumeLayout(False)
        self.PerformLayout()
        self.FormClosing += self.CheckClosing



    def CheckClosing(self, sender, e):
        if self.worker.IsBusy:
            self.worker.CancelAsync()
            e.Cancel = True
        #print "close"

    def OkayClicked(self, sender, e):
        if self._Okay.Text == "Start":
            if self.worker.IsBusy == False:
                self.worker.RunWorkerAsync()
        self._Cancel.Enabled = True
        self._Okay.Enabled = False
        #else:
            #self.DialogResult = DialogResult.OK

    def CancelClicked(self, sender, e):
        if self.worker.IsBusy:
            self.worker.CancelAsync()
        self._Cancel.Enabled = False

    def DoWork(self, sender, e):
        e.Result = getIssueCount(sender,self.books)

    def ReportProgress(self, sender, e):
        self.progresspercent = self.percentage*e.ProgressPercentage
        self._progress.Value = int(round(self.progresspercent))
        self._label1.Text = "Searching for " + e.UserState.ToString()


    def WorkerCompleted(self, sender, e):
        self._Okay.Text = "Done"
        self.Close()
        self.Dispose() 


def getIssueCount(worker,books):

    API_KEY="<API_KEY>"
    
    all_books_original = ComicRack.App.GetLibraryBooks()

    stop=False
    CheckedVolumes=list()
    IssueCountList=list()
    IssueCount=0

    failed = 0
    count = 0
    report = System.Text.StringBuilder()
    for book in books:
        if worker.CancellationPending:
            return failed,report.ToString()
        
        volume = book.GetCustomValue("comicvine_volume")
        seriesVolume = volume
        bookinfo = "#" + str(book.Number) + " " + book.Series + " (" + str(book.Volume) + ")"    
        
        count += 1
        worker.ReportProgress(count,bookinfo)

        

        if volume not in CheckedVolumes:
            QUERY = "https://comicvine.gamespot.com/api/volume/4050-"+ volume +"/?api_key=" + API_KEY + "&format=xml&field_list=count_of_issues"
            print QUERY
            data = _read_url(QUERY.encode('utf-8'))
            
            time.sleep(10)

            doc = System.Xml.XmlDocument()
            doc.LoadXml(data)
            elemList = doc.GetElementsByTagName("count_of_issues")

            for i in elemList:
                IssueCount = int(i.InnerXml)
                if i.InnerText == "":
                    failed += 1
                    report.Append(i.InnerText)
                else:
                    report.Append(i.InnerText)
                    print str(volume) + "'s count is " + str(IssueCount)
            CheckedVolumes.append(volume)
            IssueCountList.append(IssueCount)        
            
        
            for book in all_books_original:

                volume = book.GetCustomValue("comicvine_volume")
                if volume == seriesVolume:
                    if book.Number.isnumeric:
                        book.Count = IssueCount
                        book.SetCustomValue("comicvine_issue_count",str(IssueCount))

    return failed,report.ToString()

def _read_url(url):
        
    page = '' 
        
    requestUri = url

    ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls12 | SecurityProtocolType.Ssl3;

    Req = HttpWebRequest.Create(requestUri)  
    Req.Timeout = 60000
    Req.UserAgent = "CVIssueCount/" + " (https://gitea.baerentsen.space/FrederikBaerentsen/ComicRack_Scripts/src/branch/master/CVIssueCount)" 
    Req.AutomaticDecompression = DecompressionMethods.Deflate | DecompressionMethods.GZip       
    
    #Req.Referer = requestUri
    Req.Accept = 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8'
    Req.Headers.Add('Accept-Language','en-US,en;q=0.9,it;q=0.8,fr;q=0.7,de-DE;q=0.6,de;q=0.5')
    
    Req.KeepAlive = True        
    webresponse = Req.GetResponse() 

    a = webresponse.Cookies 

    inStream = webresponse.GetResponseStream()      
    encode = Encoding.GetEncoding("utf-8")
    ReadStream = StreamReader(inStream, encode)
    page = ReadStream.ReadToEnd()

            
    try:
        inStream.Close()    
        webresponse.Close()
    except:
        pass
    
    return page
