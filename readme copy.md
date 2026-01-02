## 1.Check the name of the system network card

```shell
root@ubuntu:~# ifconfig
br-d81446d4a4f6: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 172.20.0.1  netmask 255.255.0.0  broadcast 172.20.255.255
        inet6 fe80::42:efff:fe0a:cb64  prefixlen 64  scopeid 0x20<link>
        ether 02:42:ef:0a:cb:64  txqueuelen 0  (Ethernet)
        RX packets 309134  bytes 314812349 (314.8 MB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 291435  bytes 21921397 (21.9 MB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

docker0: flags=4099<UP,BROADCAST,MULTICAST>  mtu 1500
        inet 172.17.0.1  netmask 255.255.0.0  broadcast 172.17.255.255
        ether 02:42:a9:f4:36:e6  txqueuelen 0  (Ethernet)
        RX packets 0  bytes 0 (0.0 B)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 0  bytes 0 (0.0 B)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 172.18.1.235  netmask 255.255.240.0  broadcast 172.18.15.255
        inet6 fe80::216:3eff:fe18:e57d  prefixlen 64  scopeid 0x20<link>
        ether 00:16:3e:18:e5:7d  txqueuelen 1000  (Ethernet)
        RX packets 15977030  bytes 2837994640 (2.8 GB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 15696860  bytes 6111767699 (6.1 GB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```

 

##	2.Modify the network card name in docker-compose.yml 



 ```   shell
  cd  /esl
  vim ./docker-compose.yml
 ```



![](./img/eth0.png)

## 3.Run script

```shell
chmod +x  ./install_esl.bash

./install_esl.bash
```

## 4.After installation, access the server domain name

![](./img/license.png)

# 5Enable system data backup

![image-20241126103249047](./img/mysql.png)





## 5.Find Us and we will help you  activate system
