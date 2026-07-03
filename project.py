import boto3
session=boto3.session.Session()
cli_obj=session.client(service_name="ec2", region_name="us-east-1")
res_obj=session.resource(service_name="ec2", region_name="us-east-1")

# 1- Create a new VPC
my_vpc = cli_obj.create_vpc( CidrBlock='10.0.0.0/16')
vpc_ID=my_vpc['Vpc']['VpcId']
print(f"the vpc has been created successfully with id {vpc_ID}")

# 2- Create public subnets
azs=["us-east-1a","us-east-1b"]
public_cidr=["10.0.10.0/24","10.0.20.0/24"]
public_sub_id=[]
for cidr, az in zip(public_cidr, azs): 
    sub=cli_obj.create_subnet(AvailabilityZone=az,CidrBlock=cidr,VpcId=vpc_ID)
    public_sub_id.append(sub['Subnet']['SubnetId'])
print(f"Public Subnets have been created successfully , their ids are {public_sub_id[0]} and {public_sub_id[1]}")

# 3- Enable auto-assign public IP addresses for public subnets
for subnet in public_sub_id:
    cli_obj.modify_subnet_attribute( SubnetId=subnet,MapPublicIpOnLaunch={'Value': True})

# 4- Create private subnets
private_cidr=["10.0.100.0/24","10.0.200.0/24"]
private_sub_id=[]
for cidr, az in zip(private_cidr, azs): 
    pri_sub=cli_obj.create_subnet(AvailabilityZone=az,CidrBlock=cidr,VpcId=vpc_ID)
    private_sub_id.append(pri_sub['Subnet']['SubnetId'])
print(f"Public Subnets have been created successfully , their ids are {private_sub_id[0]} and {private_sub_id[1]}") 

# 5- Create the Internet Gateway
igw=cli_obj.create_internet_gateway()
igw_id=igw['InternetGateway']['InternetGatewayId']
print(f"the internet gateway has been created successfully with id {igw_id}")

# 6- attach the Internet Gateway to the new VPC
response5 = cli_obj.attach_internet_gateway( InternetGatewayId=igw_id,VpcId=vpc_ID)

# 7- Create route table for public subnets to route traffic through Internet Gateway
public_rt=cli_obj.create_route_table(VpcId=vpc_ID)
public_RT_id=public_rt['RouteTable']['RouteTableId']
print(f"The New Route Table for public subnets have been created successfully with id {public_RT_id}")

# 8- Associate public subnets to public route table
for subnet in public_sub_id:
    response = cli_obj.associate_route_table(SubnetId=subnet,RouteTableId=public_RT_id)
    
# 9 - add the default route in public route table towards Internet Gateway
response = cli_obj.create_route(DestinationCidrBlock='0.0.0.0/0',GatewayId=igw_id,RouteTableId=public_RT_id,)

# 10- Create NAT Gateway for private subnets
allocation = cli_obj.allocate_address( Domain='vpc')    #allocate an elastic ip for NAT

natgw = cli_obj.create_nat_gateway(AllocationId=allocation['AllocationId'], SubnetId=public_sub_id[0])
nat_id=natgw['NatGateway']['NatGatewayId']
print(f"NAT Gateway has been created successfully , its id is {nat_id}")

#11- Create route table for private subnets to route traffic through NAT Gateway
private_rt=cli_obj.create_route_table(VpcId=vpc_ID)
private_RT_id=private_rt['RouteTable']['RouteTableId']
print(f"The New Route Table for private subnets have been created successfully with id {private_RT_id}")

# 12- Associate private subnets to private route table
for subnet in private_sub_id:
    response = cli_obj.associate_route_table(SubnetId=subnet,RouteTableId=private_RT_id)
    
#13 - Ensuring NAT Gateway is up and available 
waiter = cli_obj.get_waiter('nat_gateway_available')
print("the nat gateway is starting now please wait")
waiter.wait(NatGatewayIds=[nat_id])
print("the nat GW is ready now")

# 14 - add the default route in private route table towards NAT Gateway
response2 = cli_obj.create_route(DestinationCidrBlock='0.0.0.0/0',GatewayId=nat_id,RouteTableId=private_RT_id,)

# 15 - Create the required security group for EC2 instances.
privatesg = cli_obj.create_security_group( GroupName='WebSG',VpcId=vpc_ID,Description='Private SG for EC2 Instances',)
websg_id=privatesg['GroupId']
print(f"Security Group WebSG has been created successfully , its id is {websg_id}")

# 16- Add security group ingress rules for ports [22,80,443]
ports= [22,80,443]
descriptions=["ssh access","http access","secure http access"]
for port ,decs in zip(ports,descriptions):
    response = cli_obj.authorize_security_group_ingress(
    GroupId=websg_id,
    IpPermissions=[
        {
            'FromPort': port,
            'IpProtocol': 'tcp',
            'IpRanges': [
                {
                    'CidrIp': '0.0.0.0/0',
                    'Description': decs,
                },
            ],
            'ToPort': port, },])

# 17- add egress rule to the WebSG - allowing traffic for updates and download any required packages.
response10 = cli_obj.authorize_security_group_egress(GroupId=websg_id,
    IpPermissions=[
        {
            'FromPort': 0,
            'IpProtocol': 'tcp',
            'IpRanges': [
                {
                    'CidrIp': '0.0.0.0/0',
                },
            ],
            'ToPort': 0,
        },
    ],)

# 18 - Launch EC2 instances in private subnets
user1_script='''#!/bin/bash
yum update -y
yum install httpd -y
systemctl start httpd
systemctl enable httpd
echo "This is server *1* in AWS Region US-EAST-1 in AZ US-EAST-1A" > /var/www/html/index.html'''

user2_script='''#!bin/bash
yum update -y
yum install httpd -y
systemctl start httpd# starts httpd service   
systemctl enable httpd# enable httpd to auto-start at system boot
echo " This is server *2* in AWS Region US-EAST-1 in AZ US-EAST-1B " > /var/www/html/index.html'''
user_data=[user1_script,user2_script]
instance_id=[]
for script,subn in zip(user_data,private_sub_id):
    response11 = cli_obj.run_instances(ImageId='ami-06067086cf86c58e6',InstanceType="t3.micro", MaxCount=1, MinCount=1,
        SubnetId=subn,
        UserData=script,
        BlockDeviceMappings=[
            {
                'DeviceName': '/dev/xvda',
                'Ebs': {
                    'DeleteOnTermination': True,
                    'Encrypted': True,
                    'VolumeSize': 8,
                    'VolumeType': 'gp2'
                }
            }
        ],
        SecurityGroupIds=[
        websg_id
    ],)
    instance_id.append(response11["Instances"][0]['InstanceId'])  
    
''' 19 - Ensuring all instances are in running State'''
waiter = cli_obj.get_waiter('instance_running')  
print("the intances are pending please wait")
waiter.wait(InstanceIds=instance_id)
print("the instances are running and ready now")
print(f"The new instances for Web and App have been created successfully, their ids are {instance_id[0]} and {instance_id[1]}")

''' 20 - Create Client Objects for other Services like Load Balancer , Auto Scaling, RDS'''
# A- Create a client Object for Elastic Load Balancing
elb_client = session.client('elbv2', region_name='us-east-1')

# B- Create a client object for Auto Scaling
autoscaling_client = session.client('autoscaling', region_name='us-east-1')

# C- Create a client for RDS
rds_client = session.client('rds', region_name='us-east-1')

#create target group
tg = elb_client.create_target_group(
    Name='webTG',
    Protocol='HTTP',
    Port=80,
    VpcId=vpc_ID,
    HealthCheckProtocol='HTTP',
    HealthCheckPort='80',
    HealthCheckEnabled=True
)
target_group_arn = tg['TargetGroups'][0]['TargetGroupArn']
print(f"The Target Group has been created successfully , its arn is {target_group_arn}")
# 22 - Register EC2-targets to the target grou
for inst_id in instance_id:
    response = elb_client.register_targets(
    TargetGroupArn=target_group_arn,
    Targets=[{'Id': inst_id}])
# A- Create the Load balancer Security Group
albsg = cli_obj.create_security_group( GroupName='albSG',VpcId=vpc_ID,Description=' SG for alb',)
albsg_id=albsg['GroupId']
print(f"Security Group albSG has been created successfully , its id is {albsg_id}")

# B- add ingress rule to the ALB SG , allowing HTTP Traffic inbound
response = cli_obj.authorize_security_group_ingress(
    GroupId=albsg_id,
    IpPermissions=[
        {
            'FromPort': 80,
            'IpProtocol': 'tcp',
            'IpRanges': [
                {
                    'CidrIp': '0.0.0.0/0',
                    'Description': "allow http",
                },
            ],
            'ToPort': 80, },])
# C- add egress rules to the ALB SG - allowing outbound port 80 towards WebSG security group
cli_obj.authorize_security_group_egress(
    GroupId=albsg_id,
    IpPermissions=[
        {
            'FromPort': 80,
            'IpProtocol': 'tcp',
            'ToPort': 80,
            'UserIdGroupPairs': [
                {
                    'GroupId': websg_id,
                },
            ],
        },
    ],
)

# D- creating the ALB itself
response = elb_client.create_load_balancer(
    Name='myALB',
    Subnets=public_sub_id,
    SecurityGroups=[albsg_id],
    Scheme='internet-facing',
    Type='application',
    IpAddressType='ipv4')
alb_arn=response['LoadBalancers'][0]['LoadBalancerArn']
alb_dns=response['LoadBalancers'][0]['DNSName']
''' E- Ensuring Load Balancer is available and up '''
waiter = elb_client.get_waiter('load_balancer_available')
print ("the load balancer is starting now please wait")
waiter.wait(LoadBalancerArns=[alb_arn ],)
print("Load Balancer is up and available now")
print(f"The Application Load Balancer has been created successfully , its arn is {alb_arn} and its DNS is {alb_dns}")

# 24- Create a listener for the load balancer
response = elb_client.create_listener(
    LoadBalancerArn=alb_arn,
    Protocol='HTTP',
    Port=80,
    DefaultActions=[{ 'Type': 'forward','TargetGroupArn': target_group_arn,}])

# 25- Configure the auto-scaling group
# A- Create the Launch template
response = cli_obj.create_launch_template(LaunchTemplateData={'ImageId':'ami-06067086cf86c58e6','InstanceType':'t3.micro','SecurityGroupIds':[websg_id ]},
    LaunchTemplateName='my-launch-template',)
la_temp_id=response['LaunchTemplate']['LaunchTemplateId']

# B- Create the auto-scaling group
response = autoscaling_client.create_auto_scaling_group(
    AutoScalingGroupName='my_scaling_group',
    LaunchTemplate={'LaunchTemplateId': la_temp_id},
    MinSize=1,
    MaxSize=3,
    DesiredCapacity=1,
    TargetGroupARNs=[target_group_arn, ],
    AvailabilityZones=azs)
response = autoscaling_client.describe_auto_scaling_groups(
    AutoScalingGroupNames=['my_scaling_group',],)
asg_arn=response['AutoScalingGroups'][0]['AutoScalingGroupARN']
print(f"The Auto Scaling Group has been created successfully , its arn is {asg_arn}" )

''' 25 - create the RDS DataBase and its security group'''
# A- Create a DB security group
DB_SG = cli_obj.create_security_group(
    Description='SG for Database',
    GroupName='db_SG',
    VpcId=vpc_ID,
    TagSpecifications=[
        {
            'ResourceType': 'security-group',
            'Tags': [
                {
                    'Key': 'Name',
                    'Value': 'DB_SG'
                },
            ]
        },
    ],
)
DB_SG_ID = DB_SG['GroupId']
print(f"Security Group DB_SG has been created successfully , its id is {DB_SG_ID}")
# B- Authorize inbound access to the DB security group from only WebSG security group
cli_obj.authorize_security_group_ingress(
    GroupId=DB_SG_ID,
    IpPermissions=[
        {
            'FromPort': 0,
            'ToPort': 0,
            'IpProtocol': '-1',
            'UserIdGroupPairs': [
                {
                    'GroupId': websg_id,
                },
            ],
        },
    ],
)
# C - Create the DB Subnet Group
rds_client.create_db_subnet_group(
    DBSubnetGroupDescription='RDS Databases Subnet Group',
    DBSubnetGroupName='myrdsdbsubnetgroup1',
    SubnetIds=private_sub_id
)
# D- Launch The Multi-AZ RDS database
response = rds_client.create_db_instance(
    DBInstanceIdentifier='myrds',
    DBInstanceClass='db.t3.micro',
    Engine='mysql',
    AllocatedStorage=10,
    MasterUsername='admin',
    MasterUserPassword='webdbmomomomo',
    DBSubnetGroupName='myrdsdbsubnetgroup1',
    VpcSecurityGroupIds=[DB_SG_ID, ],
    MultiAZ=True
)
rds_arn = response['DBInstance']['DBInstanceArn']
waiter = rds_client.get_waiter('db_instance_available')
print("RDS Instance is being started ......")
waiter.wait(DBInstanceIdentifier='myrds')
print("RDS Instance is up and available now")
rds = rds_client.describe_db_instances(DBInstanceIdentifier='myrds')
rds_address = rds['DBInstances'][0]['Endpoint']['Address']
print(f"The RDS Instance DB has been created successfully , its arn is {rds_arn} and its DNS Address is {rds_address}")








       
    


    




    