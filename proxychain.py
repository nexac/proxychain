import socket, select, time, sys, re, struct, random

# define chain type
DYNAMIC_CHAIN = 1
STRICT_CHAIN = 2
RANDOM_CHAIN = 3

# global var
delay = 0.001
buffer_size = 4096
ChainType = DYNAMIC_CHAIN
ChainLength = 0
ProxyList = []
ProxyDict = {}

# Load proxychain.conf
with open('proxychain.conf', 'r', encoding='utf-8') as conf:
    for line in conf.read().splitlines():
        if line.startswith('#') or '' == line:
            continue

        if 'dynamic_chain' == line:
            ChainType = DYNAMIC_CHAIN
        elif 'strict_chain' == line:
            ChainType = STRICT_CHAIN
        elif 'random_chain' == line:
            ChainType = RANDOM_CHAIN
            
        elif 'chain_len' in line:
            ChainLength = int(line.split('=')[-1].split(' ')[-1])

        elif not line.startswith('[ProxyList]'):
            proto, ip, port = line.split(' ')
            ProxyList.append(ip + ':' + port)
            ProxyDict.update({ip + ':' + port: proto})
            
if not ProxyList:
    print('Proxy list empty!\n')
    sys.exit(0)

class ProxyChain:
    SocketList = []
    SocketDict = {}

    def __init__(self, host, port):
        self.RelaySock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.RelaySock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.RelaySock.bind((host, port))
        self.RelaySock.listen()

    def Main(self):
        self.SocketList.append(self.RelaySock)
        while 1:
            time.sleep(delay)
            try:
                readable, writable, exceptional = select.select(self.SocketList, [], [])
                for self.sock in readable:
                    if self.sock == self.RelaySock:
                        self.AcceptConnection()                
                        break

                    self.data = self.MyRecv(self.sock)
                    if 0 == len(self.data):
                        self.CloseConnection()
                        break
                    else:
                        self.SocketDict[self.sock].send(self.data)
            except:
                pass

    def AcceptConnection(self):
        self.ClientSock, ClientAddr = self.RelaySock.accept()

        self.ByteData = self.MyRecv(self.ClientSock)
        if 0 == len(self.ByteData):
            self.ClientSock.close()
            return
            
        if 0x05 == self.ByteData[0] and 3 == len(self.ByteData):
            RemoteName, RemotePort = self.socks5()
            RemoteType = 'socks5'
        elif 0x04 == self.ByteData[0]:
            RemoteName, RemotePort = self.socks4()
            RemoteType = 'socks4'
        else:
            RemoteName, RemotePort = self.http()
            RemoteType = 'http'

        if '' == RemoteName or '' == RemotePort:
            self.ClientSock.close()
            return

        if STRICT_CHAIN == ChainType:
            Ret = self.StrictChain(RemoteName, RemotePort, RemoteType)
        elif DYNAMIC_CHAIN == ChainType:
            Ret = self.DynamicChain(RemoteName, RemotePort, RemoteType)
        elif RANDOM_CHAIN == ChainType:
            Ret = self.RandomChain(RemoteName, RemotePort, RemoteType)

        if False == Ret:
            self.ClientSock.close()
            return 
        
        # bind client and remote socket
        self.SocketList.append(self.ClientSock)
        self.SocketList.append(self.RemoteSock)
        self.SocketDict[self.ClientSock] = self.RemoteSock
        self.SocketDict[self.RemoteSock] = self.ClientSock
        
    def CloseConnection(self):
        self.sock.close()
        self.SocketDict[self.sock].close()
        
        self.SocketList.remove(self.sock)
        self.SocketList.remove(self.SocketDict[self.sock])
        
        del self.SocketDict[self.SocketDict[self.sock]]
        del self.SocketDict[self.sock]
    
    def socks5(self):
        self.MySend(self.ClientSock, b'\x05\x00')
        self.ByteData = self.MyRecv(self.ClientSock)
        
        try:
            if 0x05 != self.ByteData[0] or 0x01 != self.ByteData[1]:
                self.MySend(self.ClientSock, b'\x05\x07\x00\x00\x00\x00\x00\x00\x00\x00')
                return ('', '')
            
            RemotePort = str((self.ByteData[-2] << 8) | self.ByteData[-1])
            if 0x01 == self.ByteData[3]:
                RemoteIP = str(self.ByteData[4]) + '.' + str(self.ByteData[5]) + '.' + \
                            str(self.ByteData[6]) + '.' + str(self.ByteData[7])
                return (RemoteIP, RemotePort)
            elif 0x03 == self.ByteData[3]:
                RemoteDomain = ''
                for iter in range(5, (5+self.ByteData[4])):
                    RemoteDomain += str(chr(self.ByteData[iter]))
                return (RemoteDomain, RemotePort)
        except:
            return ('', '')
    
    def socks4(self):
        if 0x01 != self.ByteData[1]:
            self.MySend(self.ClientSock, b'\x00\x5B\x00\x00\x00\x00\x00\x00')
            return ('', '')
        
        RemotePort = str((self.ByteData[2] << 8) | self.ByteData[3])
        RemoteIP = str(self.ByteData[4]) + '.' + str(self.ByteData[5]) + '.' + \
                    str(self.ByteData[6]) + '.' + str(self.ByteData[7])
        
        return (RemoteIP, RemotePort)
    
    def http(self):
        DecodeData = self.ByteData.partition(b'\r\n\r\n')[0].decode()
        
        try:
            FirstLine = DecodeData.split('\r\n')[0]
            HTTP_method, content, HTTP_version = FirstLine.split(' ')
        except:
            return ('', '')
        
        if 'CONNECT' == HTTP_method:
            RemoteDomain, RemotePort = content.split(':')
        else:
            RemoteDomain = ''
            for line in DecodeData.split('\r\n'):
                if 'Host:' in line:
                    RemoteDomain = line.split('Host: ')[-1]
            
            if 0 == len(RemoteDomain):
                return ('', '')       
            RemotePort = '80'
        
        return (RemoteDomain, RemotePort)
    
    def StrictChain(self, RemoteName, RemotePort, RemoteType):
        ChainInfo = ''
        for iter, proxy in enumerate(ProxyList):
            ip, port = proxy.split(':')

            # connect chain head
            if ProxyList[0] == proxy:
                try:
                    self.RemoteSock = socket.create_connection((ip, port), timeout=5)
                    ChainInfo += '|S-chain|-<>-%s:%s' % (ip, port)
                except:
                    if 'http' == proto:
                        self.MySend(self.ClientSock, b'HTTP/1.1 408 Request Timeout\r\n\r\n')
                    elif 'socks4' == proto:
                        self.MySend(self.ClientSock, b'\x00\x5B\x00\x00\x00\x00\x00\x00')
                    elif 'socks5' == proto:
                        self.MySend(self.ClientSock, b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
                    ChainInfo += '|S-chain|-><-%s:%s' % (ip, port)
                    print(ChainInfo)
                    return False    
                        
            # begin chaining
            else:
                if 'http' == ProxyDict[ProxyList[iter-1]]:
                    self.MySend(self.RemoteSock, ('CONNECT %s:%s HTTP/1.1\r\n\r\n' % (ip, port)).encode())
                elif 'socks4' == ProxyDict[ProxyList[iter-1]]:
                    self.MySend(self.RemoteSock, b'\x04\x01' + int(port).to_bytes(2, 'big') + \
                                bytes(map(int, ip.split('.'))) + b'\x00')
                elif 'socks5' == ProxyDict[ProxyList[iter-1]]:
                    self.Socks5Greeting()
                    self.MySend(self.RemoteSock, b'\x05\x01\x00\x01' + bytes(map(int, ip.split('.'))) + \
                                int(port).to_bytes(2, 'big'))                    
                    
                RecvData = self.MyRecv(self.RemoteSock)
                try:
                    if (0 == len(RecvData)) or \
                        ('http' == ProxyDict[ProxyList[iter-1]] and b'HTTP/1.1 4' in RecvData) or \
                        ('socks4' == ProxyDict[ProxyList[iter-1]] and 0x5A != RecvData[1]) or \
                        ('socks5' == ProxyDict[ProxyList[iter-1]] and 0x00 != RecvData[1]):
                        self.RemoteSock.close()
                        ChainInfo += '-><-%s:%s' % (ip, port)
                        self.MySend(self.ClientSock, RecvData)
                        print(ChainInfo)
                        return False
                except:
                        self.RemoteSock.close()
                        ChainInfo += '-><-%s:%s' % (ip, port)
                        print(ChainInfo)
                        return False                    
                
                ChainInfo += '-<>-%s:%s' % (ip, port)

        if False == self.ConnectRemote(RemoteType):
            ChainInfo += '- >< -%s:%s' % (RemoteName, RemotePort)
            print(ChainInfo)
            return False
        
        ChainInfo += '-<><>-%s:%s' % (RemoteName, RemotePort)
        print(ChainInfo)
        return True
    
    def DynamicChain(self, RemoteName, RemotePort, RemoteType):
        ChainInfo = ''
        ChainHead = -1     
        for iter, proxy in enumerate(ProxyList):
            ip, port = proxy.split(':')
            
            # find chain head
            if -1 == ChainHead:
                try:
                    self.RemoteSock = socket.create_connection((ip, port), timeout=5)
                    ChainHead = iter
                    ChainInfo += '|D-chain|-<>-%s:%s' % (ip, port)
                except:
                    if ProxyList[-1] == proxy:
                        ChainInfo += '|D-chain| No online proxy!'
                        print(ChainInfo)
                        return False
            
            # begin chaining
            else:
                if 'http' == ProxyDict[ProxyList[iter-1]]:
                    self.MySend(self.RemoteSock, ('CONNECT %s:%s HTTP/1.1\r\n\r\n' % (ip, port)).encode())
                elif 'socks4' == ProxyDict[ProxyList[iter-1]]:
                    self.MySend(self.RemoteSock, b'\x04\x01' + int(port).to_bytes(2, 'big') + \
                                bytes(map(int, ip.split('.'))) + b'\x00')
                elif 'socks5' == ProxyDict[ProxyList[iter-1]]:
                    self.Socks5Greeting()
                    self.MySend(self.RemoteSock, b'\x05\x01\x00\x01' + bytes(map(int, ip.split('.'))) + \
                                int(port).to_bytes(2, 'big'))    
                    
                RecvData = self.MyRecv(self.RemoteSock)
                try:
                    if (0 == len(RecvData)) or \
                        ('http' == ProxyDict[ProxyList[iter-1]] and b'HTTP/1.1 4' in RecvData) or \
                        ('socks4' == ProxyDict[ProxyList[iter-1]] and 0x5A != RecvData[1]) or \
                        ('socks5' == ProxyDict[ProxyList[iter-1]] and 0x00 != RecvData[1]):
                        self.RemoteSock.close()
                        ip, port = ProxyList[ChainHead].split(':')
                        self.RemoteSock = socket.create_connection((ip, port), timeout=5)
                        continue
                except:
                    continue
                
                ChainInfo += '-<>-%s:%s' % (ip, port)
        
        if False == self.ConnectRemote(RemoteType):
            ChainInfo += '- >< -%s:%s' % (RemoteName, RemotePort)
            print(ChainInfo)
            return False
        
        ChainInfo += '-<><>-%s:%s' % (RemoteName, RemotePort)
        print(ChainInfo)
        return True
    
    def RandomChain(self, RemoteName, RemotePort, RemoteType):
        if 0 == ChainLength:
            print('|R-Chain| chain length is 0!')
            return False
        
        ChainInfo = ''
        ChainHeadIP, ChainHeadPort = '', ''
        for iter, proxy in enumerate(random.sample(ProxyList, ChainLength)):
            ip, port = proxy.split(':')

            # connect chain head
            if ('', '') == (ChainHeadIP, ChainHeadPort):
                try:
                    self.RemoteSock = socket.create_connection((ip, port), timeout=5)
                    ChainHeadIP, ChainHeadPort = ip, port
                    ChainInfo += '|R-chain|-<>-%s:%s' % (ip, port)
                except:
                    if 'http' == proto:
                        self.MySend(self.ClientSock, b'HTTP/1.1 408 Request Timeout\r\n\r\n')
                    elif 'socks4' == proto:
                        self.MySend(self.ClientSock, b'\x00\x5B\x00\x00\x00\x00\x00\x00')
                    elif 'socks5' == proto:
                        self.MySend(self.ClientSock, b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
                    ChainInfo += '|R-chain|-><-%s:%s' % (ip, port)
                    print(ChainInfo)
                    return False
                
            # begin chaining
            else:
                if 'http' == ProxyDict[ProxyList[iter-1]]:
                    self.MySend(self.RemoteSock, ('CONNECT %s:%s HTTP/1.1\r\n\r\n' % (ip, port)).encode())
                elif 'socks4' == ProxyDict[ProxyList[iter-1]]:
                    self.MySend(self.RemoteSock, b'\x04\x01' + int(port).to_bytes(2, 'big') + \
                        bytes(map(int, ip.split('.'))) + b'\x00')
                elif 'socks5' == ProxyDict[ProxyList[iter-1]]:
                    self.Socks5Greeting()
                    self.MySend(self.RemoteSock, b'\x05\x01\x00\x01' + bytes(map(int, ip.split('.'))) + \
                                int(port).to_bytes(2, 'big'))
                
                RecvData = self.MyRecv(self.RemoteSock)
                try:
                    if (0 == len(RecvData)) or \
                        ('http' == ProxyDict[ProxyList[iter-1]] and b'HTTP/1.1 4' in RecvData) or \
                        ('socks4' == ProxyDict[ProxyList[iter-1]] and 0x5A != RecvData[1]) or \
                        ('socks5' == ProxyDict[ProxyList[iter-1]] and 0x00 != RecvData[1]):
                        self.RemoteSock.close()
                        self.RemoteSock = socket.create_connection((ChainHeadIP, ChainHeadPort), timeout=5)
                        continue
                except:
                    continue
                    
                ChainInfo += '-<>-%s:%s' % (ip, port)
        
        if False == self.ConnectRemote(RemoteType):
            ChainInfo += '- >< -%s:%s' % (RemoteName, RemotePort)
            print(ChainInfo)
            return False
        
        ChainInfo += '-<><>-%s:%s' % (RemoteName, RemotePort)
        print(ChainInfo)
        return True 

    def MySend(self, sock, Data):
        try:
            sock.send(Data)
            return True
        except:
            return False
    
    def MyRecv(self, sock):
        try:
            for i in range(10):
                Data = sock.recv(buffer_size)
                if 0 != len(Data):
                    break
            return Data
        except:
            return b''
    
    def ConnectRemote(self, RemoteType):
        if 'socks5' == RemoteType:
            self.Socks5Greeting()

        self.MySend(self.RemoteSock, self.ByteData)

        self.ByteData = self.MyRecv(self.RemoteSock)
        if 0 == len(self.ByteData):
            self.RemoteSock.close()
            return False
            
        self.MySend(self.ClientSock, self.ByteData)

        if 'http' == RemoteType and b'HTTP/1.1 4' in self.ByteData:
            self.RemoteSock.close()
            return False
        elif 'socks4' == RemoteType and 0x5A != self.ByteData[1]:
            self.RemoteSock.close()
            return False
        elif 'socks5' == RemoteType and 0x00 != self.ByteData[1]:
            self.RemoteSock.close()
            return False

        return True
    
    def Socks5Greeting(self):
        self.MySend(self.RemoteSock, b'\x05\x00\x00')
        self.MyRecv(self.RemoteSock)
    
if __name__ == '__main__':
    proxychain = ProxyChain('', 9999)
    try:
        proxychain.Main()
    except KeyboardInterrupt:
        print('Proxychain stopped!!')
        sys.exit(1)