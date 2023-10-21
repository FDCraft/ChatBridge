CommandHelpMessage = '''
`!!help`: 显示这条消息
`!!ping`: pong!!
`!!stats`: 显示stats指令的帮助信息
`!!online`: 显示服务器玩家在线状态
'''.strip()


StatsCommandHelpMessage = '''
`!!stats rank <类别> <内容> [<-bot>] [<-all>]`
添加`-bot`显示包含bot的排名（bot过滤逻辑挺简陋的）
添加`-all`显示所有玩家的排名，刷屏预警
`<类别>`: `killed`, `killed_by`, `dropped`, `picked_up`, `used`, `mined`, `broken`, `crafted`, `custom`
更多详情见：[统计信息wiki](https://wiki.biligame.com/mc/%E7%BB%9F%E8%AE%A1%E4%BF%A1%E6%81%AF)
例子:
`!!stats rank used diamond_pickaxe`
`!!stats rank custom time_since_rest -bot`
'''.strip()
