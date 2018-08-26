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
            if ChainType == RANDOM_CHAIN and ChainLength < 2:
                print('|R-chain| chain_len less than 2!')
                sys.exit(0)

        elif not line.startswith('[ProxyList]'):
            # (protocol, ip, port)
            ProxyList.append(tuple(line.split(' ')))

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

            except KeyboardInterrupt:
                print('Proxychain stopped!!')
                sys.exit(1)
            except:
                pass

    def AcceptConnection(self):
        self.ClientSock, ClientAddr = self.RelaySock.accept()

        self.ByteData = self.MyRecv(self.ClientSock)

        if 0 == len(self.ByteData):
            self.ClientSock.close()
            return

        # parse remote address
        if 0x05 == self.ByteData[0] and len(self.ByteData) == (self.ByteData[1] + 2):
            Remote = self.socks5()
        elif 0x04 == self.ByteData[0] and 0x00 == self.ByteData[-1]:
            Remote = self.socks4()
        else:
            Remote = self.http()

        # error parsing remote address
        if Remote is None:
            self.ClientSock.close()
            return

        # proxy chaining
        if STRICT_CHAIN == ChainType:
            Ret = self.StrictChain(Remote)
        elif DYNAMIC_CHAIN == ChainType:
            Ret = self.DynamicChain(Remote)
        elif RANDOM_CHAIN == ChainType:
            Ret = self.RandomChain(Remote)

        if False == Ret:
            if 'http' == Remote[0]:
                self.ClientSock.send(b'HTTP/1.1 408 Request Timeout\r\n\r\n')
            elif 'socks4' == Remote[0]:
                self.ClientSock.send(b'\x00\x5B\x00\x00\x00\x00\x00\x00')
            elif 'socks5' == Remote[0]:
                self.ClientSock.send(b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
            self.ClientSock.close()
            return
        else:
            if 'http' == Remote[0]:
                self.ClientSock.send(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            elif 'socks4' == Remote[0]:
                self.ClientSock.send(b'\x04\x5A\x00\x00\x00\x00\x00\x00')
            elif 'socks5' == Remote[0]:
                self.ClientSock.send(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')

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
        self.ClientSock.send(b'\x05\x00')
        self.ByteData = self.MyRecv(self.ClientSock)

        try:
            # command not supported
            if 0x05 != self.ByteData[0] or 0x01 != self.ByteData[1]:
                self.ClientSock.send(b'\x05\x07\x00\x00\x00\x00\x00\x00\x00\x00')
                return

            RemotePort = str((self.ByteData[-2] << 8) | self.ByteData[-1])
            # ipv4
            if 0x01 == self.ByteData[3]:
                RemoteName = str(self.ByteData[4]) + '.' + str(self.ByteData[5]) + '.' + \
                            str(self.ByteData[6]) + '.' + str(self.ByteData[7])
            # domain name
            elif 0x03 == self.ByteData[3]:
                RemoteName = ''
                for iter in range(5, (5+self.ByteData[4])):
                    RemoteName += str(chr(self.ByteData[iter]))

            return ('socks5', RemoteName, RemotePort)
        except:
            self.ClientSock.send(b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
            return

    def socks4(self):
        if 0x01 != self.ByteData[1]:
            self.ClientSock.send(b'\x00\x5B\x00\x00\x00\x00\x00\x00')
            return

        RemotePort = str((self.ByteData[2] << 8) | self.ByteData[3])
        RemoteIP = str(self.ByteData[4]) + '.' + str(self.ByteData[5]) + '.' + \
                    str(self.ByteData[6]) + '.' + str(self.ByteData[7])

        return ('socks4', RemoteIP, RemotePort)

    def http(self):
        DecodeData = self.ByteData.partition(b'\r\n\r\n')[0].decode()

        try:
            FirstLine = DecodeData.split('\r\n')[0]
            HTTP_method, content, HTTP_version = FirstLine.split(' ')
        except:
            self.ClientSock.send(b'HTTP/1.1 404 Not Found\r\n\r\n')
            return

        if 'CONNECT' == HTTP_method:
            RemoteName, RemotePort = content.split(':')
        else:
            RemoteName = ''
            for line in DecodeData.split('\r\n'):
                if 'Host:' in line:
                    RemoteName = line.split('Host: ')[-1]

            if 0 == len(RemoteName):
                self.ClientSock.send(b'HTTP/1.1 404 Not Found\r\n\r\n')
                return
            RemotePort = '80'

        return ('http', RemoteName, RemotePort)

    def StrictChain(self, Remote):
        ChainInfo = '|S-chain|'
        for iter, proxy in enumerate(ProxyList):
            # connect chain head
            if ProxyList[0] == proxy:
                try:
                    self.RemoteSock = socket.create_connection((proxy[1], proxy[2]), timeout=5)
                    ChainInfo += '-<>-%s:%s' % (proxy[1], proxy[2])
                except:
                    ChainInfo += '-><-%s:%s' % (proxy[1], proxy[2])
                    print(ChainInfo)
                    return False

            # begin chaining
            else:
                if 'http' == ProxyList[iter-1][0]:
                    self.RemoteSock.send(('CONNECT %s:%s HTTP/1.1\r\n\r\n' % (proxy[1], proxy[2])).encode())

                elif 'socks4' == ProxyList[iter-1][0]:
                    self.RemoteSock.send(b'\x04\x01' + int(proxy[2]).to_bytes(2, 'big') + \
                        bytes(map(int, proxy[1].split('.'))) + b'\x00')

                elif 'socks5' == ProxyList[iter-1][0]:
                    self.Socks5Greeting()
                    self.RemoteSock.send(b'\x05\x01\x00\x01' + bytes(map(int, proxy[1].split('.'))) + \
                        int(proxy[2]).to_bytes(2, 'big'))

                RecvData = self.MyRecv(self.RemoteSock)

                try:
                    if (0 == len(RecvData)) or \
                        ('http' == ProxyList[iter-1][0] and b'HTTP/1.1 4' in RecvData) or \
                        ('socks4' == ProxyList[iter-1][0] and 0x5A != RecvData[1]) or \
                        ('socks5' == ProxyList[iter-1][0] and 0x00 != RecvData[1]):
                        self.RemoteSock.close()
                        ChainInfo += '-><-%s:%s' % (proxy[1], proxy[2])
                        print(ChainInfo)
                        return False
                except:
                        self.RemoteSock.close()
                        ChainInfo += '-><-%s:%s' % (proxy[1], proxy[2])
                        print(ChainInfo)
                        return False

                ChainInfo += '-<>-%s:%s' % (proxy[1], proxy[2])

        if False == self.ConnectRemote(Remote, ProxyList):
            ChainInfo += '- >< -%s:%s' % (Remote[1], Remote[2])
            print(ChainInfo)
            return False

        ChainInfo += '-<><>-%s:%s' % (Remote[1], Remote[2])
        print(ChainInfo)
        return True

    def DynamicChain(self, Remote):
        ChainInfo = '|D-chain|'
        iter = 0
        TempList = ProxyList.copy()
        while iter < len(TempList):
            # find chain head
            if iter == 0:
                try:
                    self.RemoteSock = socket.create_connection((TempList[iter][1], TempList[iter][2]), timeout=5)
                    ChainInfo += '-<>-%s:%s' % (TempList[iter][1], TempList[iter][2])
                except:
                    TempList.remove(TempList[iter])
                    if not TempList:
                        ChainInfo += 'No online proxy!'
                        print(ChainInfo)
                        return False
                    continue

            # begin chaining
            else:
                if 'http' == TempList[iter-1][0]:
                    self.RemoteSock.send(('CONNECT %s:%s HTTP/1.1\r\n\r\n' % \
                        (TempList[iter][1], TempList[iter][2])).encode())

                elif 'socks4' == TempList[iter-1][0]:
                    self.RemoteSock.send(b'\x04\x01' + \
                        int(TempList[iter][2]).to_bytes(2, 'big') + \
                        bytes(map(int, TempList[iter][1].split('.'))) + b'\x00')

                elif 'socks5' == TempList[iter-1][0]:
                    self.Socks5Greeting()
                    self.RemoteSock.send(b'\x05\x01\x00\x01' + \
                        bytes(map(int, TempList[iter][1].split('.'))) + \
                        int(TempList[iter][2]).to_bytes(2, 'big'))

                RecvData = self.MyRecv(self.RemoteSock)

                try:
                    if (0 == len(RecvData)) or \
                        ('http' == TempList[iter-1][0] and b'HTTP/1.1 4' in RecvData) or \
                        ('socks4' == TempList[iter-1][0] and 0x5A != RecvData[1]) or \
                        ('socks5' == TempList[iter-1][0] and 0x00 != RecvData[1]):
                        self.RemoteSock.close()
                        TempList.remove(TempList[iter])
                        iter = 1
                        self.RemoteSock = socket.create_connection((TempList[0][1], TempList[0][2]), timeout=5)
                        continue
                except:
                    continue

                ChainInfo += '-<>-%s:%s' % (TempList[iter][1], TempList[iter][2])

            iter += 1

        if False == self.ConnectRemote(Remote, TempList):
            ChainInfo += '- >< -%s:%s' % (Remote[1], Remote[2])
            print(ChainInfo)
            return False

        ChainInfo += '-<><>-%s:%s' % (Remote[1], Remote[2])
        print(ChainInfo)
        return True

    def RandomChain(self, Remote):
        ChainInfo = '|R-chain|'
        iter = 0
        TempList = random.sample(ProxyList, ChainLength)
        while iter < len(TempList):
            # find chain head
            if iter == 0:
                try:
                    self.RemoteSock = socket.create_connection((TempList[iter][1], TempList[iter][2]), timeout=5)
                    ChainInfo += '-<>-%s:%s' % (TempList[iter][1], TempList[iter][2])
                except:
                    TempList.remove(TempList[iter])
                    if not TempList:
                        ChainInfo += 'No online proxy!'
                        print(ChainInfo)
                        return False
                    continue

            # begin chaining
            else:
                if 'http' == TempList[iter-1][0]:
                    self.RemoteSock.send(('CONNECT %s:%s HTTP/1.1\r\n\r\n' % \
                        (TempList[iter][1], TempList[iter][2])).encode())

                elif 'socks4' == TempList[iter-1][0]:
                    self.RemoteSock.send(b'\x04\x01' + \
                        int(TempList[iter][2]).to_bytes(2, 'big') + \
                        bytes(map(int, TempList[iter][1].split('.'))) + b'\x00')

                elif 'socks5' == TempList[iter-1][0]:
                    self.Socks5Greeting()
                    self.RemoteSock.send(b'\x05\x01\x00\x01' + \
                        bytes(map(int, TempList[iter][1].split('.'))) + \
                        int(TempList[iter][2]).to_bytes(2, 'big'))

                RecvData = self.MyRecv(self.RemoteSock)

                try:
                    if (0 == len(RecvData)) or \
                        ('http' == TempList[iter-1][0] and b'HTTP/1.1 4' in RecvData) or \
                        ('socks4' == TempList[iter-1][0] and 0x5A != RecvData[1]) or \
                        ('socks5' == TempList[iter-1][0] and 0x00 != RecvData[1]):
                        self.RemoteSock.close()
                        TempList.remove(TempList[iter])
                        iter = 1
                        self.RemoteSock = socket.create_connection((TempList[0][1], TempList[0][2]), timeout=5)
                        continue
                except:
                    continue

                ChainInfo += '-<>-%s:%s' % (TempList[iter][1], TempList[iter][2])

            iter += 1

        if False == self.ConnectRemote(Remote, TempList):
            ChainInfo += '- >< -%s:%s' % (Remote[1], Remote[2])
            print(ChainInfo)
            return False

        ChainInfo += '-<><>-%s:%s' % (Remote[1], Remote[2])
        print(ChainInfo)
        return True

    def MyRecv(self, sock):
        return sock.recv(buffer_size)
        '''
        try:
            total_data = b''
            while 1:
                data = sock.recv(buffer_size)
                if b'' == data:
                    break
                total_data += data
            return total_data
        except:
            return total_data
        '''


    def ConnectRemote(self, Remote, ProxyList):
        if 'http' == ProxyList[-1][0]:
            self.RemoteSock.send(('CONNECT %s:%s HTTP/1.1\r\n\r\n' % (Remote[1], Remote[2])).encode())

        elif 'socks4' == ProxyList[-1][0]:
            self.RemoteSock.send(b'\x04\x01' + int(Remote[2]).to_bytes(2, 'big') + \
                bytes(map(int, Remote[1].split('.'))) + b'\x00')

        elif 'socks5' == ProxyList[-1][0]:
            Socks5Greeting()
            self.RemoteSock.send(b'\x05\x01\x00\x01' + bytes(map(int, proxy[1].split('.'))) + \
                int(proxy[2]).to_bytes(2, 'big'))

        RecvData = self.MyRecv(self.RemoteSock)

        if 0 == len(RecvData) or \
            'http' == ProxyList[-1][0] and b'HTTP/1.1 4' in RecvData or \
            'socks4' == ProxyList[-1][0] and 0x5A != RecvData[1] or \
            'socks5' == ProxyList[-1][0] and 0x00 != RecvData[1]:
            self.RemoteSock.close()
            return False

        return True

    def Socks5Greeting(self):
        self.RemoteSock.send(b'\x05\x01\x00')
        self.MyRecv(self.RemoteSock)

if __name__ == '__main__':
    proxychain = ProxyChain('', 9999)
    proxychain.Main()